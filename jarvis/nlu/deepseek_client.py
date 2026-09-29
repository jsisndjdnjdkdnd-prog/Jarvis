from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, TypeVar

from pydantic import ValidationError

from jarvis.core.config import DeepSeekSection
from jarvis.core.errors import (
    DeepSeekError,
    DeepSeekUnavailableError,
    InvalidModelResponseError,
    StorageError,
)
from jarvis.storage.repositories.deepseek import DeepSeekStatsRepository

logger = logging.getLogger(__name__)

T = TypeVar("T")

RETRY_INSTRUCTION = (
    "Your previous answer was invalid: {error}. "
    "Reply again with ONLY one valid JSON object that follows the schema exactly."
)


class ChatRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True)
class ChatTurn:
    role: ChatRole
    content: str


class DeepSeekClient:
    def __init__(
        self,
        settings: DeepSeekSection,
        api_key: str | None,
        stats: DeepSeekStatsRepository,
        on_call: Callable[[], None] | None = None,
    ) -> None:
        self._settings = settings
        self._api_key = api_key
        self._stats = stats
        self._on_call = on_call
        self._client: Any = None
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        return self._settings.enabled and bool(self._api_key)

    def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        purpose: str,
        parse: Callable[[dict[str, Any]], T],
        *,
        temperature: float | None = None,
        prior_messages: Sequence[ChatTurn] = (),
    ) -> T:
        if not self.available:
            raise DeepSeekUnavailableError("DeepSeek вимкнено або не задано DEEPSEEK_API_KEY")
        messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
        messages.extend({"role": turn.role.value, "content": turn.content} for turn in prior_messages)
        messages.append({"role": "user", "content": user_prompt})
        effective_temperature = self._settings.temperature if temperature is None else temperature
        last_error = "порожня відповідь"
        for _ in range(self._settings.max_retries + 1):
            content = self._request(messages, purpose, effective_temperature)
            try:
                return parse(self._decode(content))
            except (json.JSONDecodeError, ValidationError, ValueError) as error:
                last_error = str(error)
                logger.warning("DeepSeek повернув невалідний JSON: %s", last_error)
                messages.append({"role": "assistant", "content": content})
                messages.append({"role": "user", "content": RETRY_INSTRUCTION.format(error=last_error)})
        raise InvalidModelResponseError(last_error)

    @staticmethod
    def _decode(content: str) -> dict[str, Any]:
        stripped = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
        data = json.loads(stripped)
        if not isinstance(data, dict):
            raise ValueError("очікувався JSON-об'єкт")
        return data

    def _request(self, messages: list[dict[str, str]], purpose: str, temperature: float) -> str:
        import openai

        started = time.perf_counter()
        try:
            response = self._openai().chat.completions.create(
                model=self._settings.model,
                messages=messages,
                response_format={"type": "json_object"},
                max_tokens=self._settings.max_tokens,
                temperature=temperature,
                timeout=self._settings.timeout_seconds,
            )
        except openai.OpenAIError as error:
            self._record(purpose, False, started, None)
            raise DeepSeekError(f"Помилка запиту до DeepSeek: {error}") from error
        self._record(purpose, True, started, getattr(response, "usage", None))
        content = response.choices[0].message.content if response.choices else None
        return content or ""

    def _openai(self) -> Any:
        with self._lock:
            if self._client is None:
                from openai import OpenAI

                self._client = OpenAI(
                    api_key=self._api_key,
                    base_url=self._settings.base_url,
                    timeout=self._settings.timeout_seconds,
                    max_retries=0,
                )
            return self._client

    def _record(self, purpose: str, success: bool, started: float, usage: Any) -> None:
        latency_ms = (time.perf_counter() - started) * 1000.0
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        try:
            self._stats.record_call(purpose, success, latency_ms, prompt_tokens, completion_tokens)
        except StorageError:
            logger.exception("Не вдалося записати статистику DeepSeek")
        if self._on_call is not None:
            self._on_call()
