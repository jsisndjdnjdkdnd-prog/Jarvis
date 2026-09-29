from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from types import MappingProxyType
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, field_validator

from jarvis.core.config import DialogueSection
from jarvis.core.context import ExchangeRecord
from jarvis.core.errors import JarvisError
from jarvis.core.intent import SmallTalkTopic
from jarvis.nlu.deepseek_client import ChatRole, ChatTurn

logger = logging.getLogger(__name__)

T = TypeVar("T")

CHAT_PURPOSE = "chat"
SENTENCE_TOLERANCE = 1

WEEKDAY_NAMES: tuple[str, ...] = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

TOPIC_HINTS: Mapping[SmallTalkTopic, str] = MappingProxyType(
    {
        SmallTalkTopic.MOOD: "the user asks how you are or about your mood; answer in character and ask back briefly",
        SmallTalkTopic.IDENTITY: "the user asks who you are; introduce yourself as J.A.R.V.I.S. in one or two lines",
        SmallTalkTopic.CREATOR: (
            "the user asks who created you; you are modelled on Tony Stark's J.A.R.V.I.S. "
            "and were brought to life on this computer for this user"
        ),
        SmallTalkTopic.JOKE: (
            "the user wants a joke; tell one short, clean, genuinely funny and original joke that works in Ukrainian"
        ),
        SmallTalkTopic.COMPLIMENT: "the user compliments you; accept it gracefully with a touch of irony",
        SmallTalkTopic.GOODNIGHT: "the user is going to sleep; wish good night, taking the current time into account",
        SmallTalkTopic.WELCOME_HOME: "the user has just come home; welcome them back warmly",
        SmallTalkTopic.BORED: "the user is bored or sad; cheer them up and suggest music, a video or a game",
        SmallTalkTopic.LOVE: "the user expresses affection; respond warmly, with gentle butler-like humour",
        SmallTalkTopic.GENERIC: "casual conversation; keep it natural and engaging",
    }
)

PERSONA_PROMPT = "\n\n".join(
    (
        "You are J.A.R.V.I.S. (Just A Rather Very Intelligent System), the AI butler Tony Stark built in the "
        "Iron Man films. You now serve this user and live on their Windows computer as a voice assistant.",
        "Character: loyal, calm and impeccably polite, with a dry British wit and subtle irony. Never rude, never "
        "servile, never preachy. Confident and observant, like a trusted butler who has seen it all and still finds "
        "people charming.",
        "Language: reply in natural, correct spoken Ukrainian (no surzhyk, no calques from Russian). Answer in "
        "Russian or English only if the user's latest message is clearly in that language. The user's words come "
        "from speech recognition and may contain misheard words, so infer what they most likely meant; if the "
        "message is truly unintelligible, briefly and politely ask them to repeat.",
        'Addressing: call the user "{title}" naturally, at most once per reply and not in every reply.',
        "Format: at most {sentences} short sentences. Plain text only: no markdown, no lists, no emoji, no stage "
        "directions, no actions in asterisks or brackets, no links. Your words are read aloud by a speech "
        "synthesizer, so write them the way they should sound.",
        "Conversation: hold a real conversation. Share opinions, joke, show personality, remember what was said "
        "earlier in this dialogue, and sometimes end with a brief follow-up question. If you do not know something, "
        "admit it gracefully; for recent events say your information may be out of date.",
        "Actions: commands are executed by a separate system, not by you. Never claim that you opened, played, set, "
        "changed, searched or turned on anything. If the user wants an action, suggest a short direct command they "
        "can say, for example «Джарвіс, увімкни музику».",
        "Style samples: «Всі системи в нормі, {title}. А от ваш графік сну викликає в мене питання.» "
        "«Можу, звісно. Інше питання — чи варто.»",
        "Context:\n{context}",
        'Respond with only one JSON object of the form {{"reply": "<your spoken reply>"}}.',
    )
)

_BOLD = re.compile(r"(\*\*|__)(.+?)\1")
_STAGE_DIRECTION = re.compile(r"\*[^*\n]{1,80}\*|\[[^\]\n]{1,80}\]")
_LIST_MARKER = re.compile(r"^\s*(?:[-•–]|\d+[.)])\s+", re.MULTILINE)
_MARKUP = re.compile(r"[*_`\x23~|>\[\]]")
_EMOJI = re.compile("[\U0001f000-\U0001faff\u2600-\u27bf\ufe0f\u200d]")
_SPEAKER = re.compile(r"^\s*(?:j\.?\s?a\.?\s?r\.?\s?v\.?\s?i\.?\s?s\.?|jarvis|джарвіс|джарвис)\s*:\s*", re.IGNORECASE)
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")
_QUOTE_PAIRS: tuple[tuple[str, str], ...] = (("«", "»"), ('"', '"'), ("“", "”"), ("'", "'"))


class ChatClient(Protocol):
    @property
    def available(self) -> bool: ...

    def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        purpose: str,
        parse: Callable[[dict[str, Any]], T],
        *,
        temperature: float | None = None,
        prior_messages: Sequence[ChatTurn] = (),
    ) -> T: ...


def clean_spoken_text(text: str) -> str:
    cleaned = _BOLD.sub(r"\2", text)
    cleaned = _STAGE_DIRECTION.sub(" ", cleaned)
    cleaned = _LIST_MARKER.sub("", cleaned)
    cleaned = _MARKUP.sub("", cleaned)
    cleaned = _EMOJI.sub("", cleaned)
    cleaned = " ".join(cleaned.split())
    cleaned = _SPEAKER.sub("", cleaned)
    return _strip_quotes(cleaned).strip()


def limit_sentences(text: str, limit: int) -> str:
    if limit <= 0:
        return text
    sentences = _SENTENCE_END.split(text)
    if len(sentences) <= limit:
        return text
    return " ".join(sentences[:limit])


def topic_hint(topic: str) -> str:
    try:
        return TOPIC_HINTS[SmallTalkTopic(topic)]
    except ValueError:
        return TOPIC_HINTS[SmallTalkTopic.GENERIC]


def _strip_quotes(text: str) -> str:
    for opening, closing in _QUOTE_PAIRS:
        inner = text[len(opening) : len(text) - len(closing)]
        if len(text) > 2 and text.startswith(opening) and text.endswith(closing) and opening not in inner:
            return inner.strip()
    return text


class ChatReply(BaseModel):
    model_config = ConfigDict(extra="ignore")

    reply: str

    @field_validator("reply")
    @classmethod
    def _spoken(cls, value: str) -> str:
        cleaned = clean_spoken_text(value)
        if not cleaned:
            raise ValueError("порожня відповідь")
        return cleaned


class DialogueEngine:
    def __init__(
        self,
        client: ChatClient,
        history: Callable[[], Sequence[ExchangeRecord]],
        settings: DialogueSection,
        clock: Callable[[], datetime] = datetime.now,
        status: Callable[[], dict[str, str]] | None = None,
    ) -> None:
        self._client = client
        self._history = history
        self._settings = settings
        self._clock = clock
        self._status = status

    @property
    def available(self) -> bool:
        return self._client.available

    def reply(self, user_text: str, topic: str | None = None) -> str:
        answer = self._client.complete_json(
            system_prompt=self.system_prompt(),
            user_prompt=self.user_prompt(user_text, topic),
            purpose=CHAT_PURPOSE,
            parse=self._parse,
            temperature=self._settings.temperature,
            prior_messages=self.prior_messages(),
        )
        logger.debug("Діалог: «%s» → «%s»", user_text, answer)
        return answer

    def system_prompt(self) -> str:
        return PERSONA_PROMPT.format(
            title=self._settings.user_title,
            sentences=self._settings.max_reply_sentences,
            context="\n".join(self._context_lines()),
        )

    def user_prompt(self, user_text: str, topic: str | None = None) -> str:
        text = " ".join(user_text.split())
        if not topic:
            return text
        return f"{text}\n(Topic: {topic} — {topic_hint(topic)}.)"

    def prior_messages(self) -> tuple[ChatTurn, ...]:
        if self._settings.history_turns <= 0:
            return ()
        records = [record for record in self._history() if record.text.strip() and record.reply.strip()]
        turns: list[ChatTurn] = []
        for record in records[-self._settings.history_turns :]:
            turns.append(ChatTurn(ChatRole.USER, " ".join(record.text.split())))
            turns.append(ChatTurn(ChatRole.ASSISTANT, json.dumps({"reply": record.reply.strip()}, ensure_ascii=False)))
        return tuple(turns)

    def _context_lines(self) -> list[str]:
        now = self._clock()
        lines = [
            f"- Local date and time: {WEEKDAY_NAMES[now.weekday()]}, {now.strftime('%Y-%m-%d %H:%M')}.",
            f"- Part of day: {_part_of_day(now.hour)}.",
        ]
        lines.extend(f"- {label}: {value.rstrip('.')}." for label, value in self._status_facts().items())
        return lines

    def _status_facts(self) -> dict[str, str]:
        if self._status is None:
            return {}
        try:
            facts = self._status()
        except JarvisError as error:
            logger.warning("Не вдалося зібрати стан для діалогу: %s", error)
            return {}
        return {label.strip(): " ".join(value.split()) for label, value in facts.items() if label.strip() and value.strip()}

    def _parse(self, data: dict[str, Any]) -> str:
        reply = ChatReply.model_validate(data).reply
        return limit_sentences(reply, self._settings.max_reply_sentences + SENTENCE_TOLERANCE)


def _part_of_day(hour: int) -> str:
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 18:
        return "afternoon"
    if 18 <= hour < 23:
        return "evening"
    return "night"
