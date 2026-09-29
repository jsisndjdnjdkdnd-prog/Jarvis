from __future__ import annotations

import asyncio
import hashlib
import logging
import queue
import threading
from pathlib import Path
from typing import Any, Protocol

from jarvis.core.config import TtsSection
from jarvis.core.errors import AudioDeviceError, SpeechSynthesisError
from jarvis.core.event_bus import EventBus
from jarvis.core.events import (
    AssistantStateChanged,
    ShutdownRequested,
    SpeakRequested,
    SpeechFinished,
    SpeechStarted,
)
from jarvis.core.speech_types import AssistantState
from jarvis.speech.audio_io import AudioPlayer

logger = logging.getLogger(__name__)

COMMON_PHRASES: tuple[str, ...] = (
    "Слухаю, сер.",
    "Виконано.",
    "Виконано, сер.",
    "Так, сер.",
    "Не розчув, сер.",
    "Вибачте, сер, я не зрозумів команду.",
    "Не знайшов такої програми. Покажете, де вона?",
    "Скасовано, сер.",
    "До ваших послуг, сер.",
)

_STOP = object()


class Speaker(Protocol):
    def speak(self, text: str) -> None: ...


class EdgeTtsSpeaker:
    def __init__(self, settings: TtsSection, cache_dir: Path, player: AudioPlayer) -> None:
        self._settings = settings
        self._cache_dir = cache_dir
        self._player = player

    def speak(self, text: str) -> None:
        self._player.play_file(self.synthesize(text))

    def synthesize(self, text: str) -> Path:
        path = self._cache_path(text)
        if path.exists() and path.stat().st_size > 0:
            return path
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".part")
        try:
            asyncio.run(self._save(text, temporary))
        except Exception as error:
            temporary.unlink(missing_ok=True)
            raise SpeechSynthesisError(f"edge-tts недоступний: {error}") from error
        temporary.replace(path)
        return path

    async def _save(self, text: str, path: Path) -> None:
        import edge_tts

        communicate = edge_tts.Communicate(
            text, self._settings.voice, rate=self._settings.rate, volume=self._settings.volume
        )
        await communicate.save(str(path))

    def _cache_path(self, text: str) -> Path:
        key = f"{self._settings.voice}|{self._settings.rate}|{self._settings.volume}|{text}"
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
        return self._cache_dir / f"{digest}.mp3"


class Pyttsx3Speaker:
    def __init__(self) -> None:
        self._engine: Any = None

    def speak(self, text: str) -> None:
        engine = self._ensure_engine()
        try:
            engine.say(text)
            engine.runAndWait()
        except RuntimeError as error:
            raise SpeechSynthesisError(f"pyttsx3: {error}") from error

    def _ensure_engine(self) -> Any:
        if self._engine is not None:
            return self._engine
        import pyttsx3

        try:
            engine = pyttsx3.init()
        except (RuntimeError, OSError) as error:
            raise SpeechSynthesisError(f"pyttsx3 недоступний: {error}") from error
        self._select_voice(engine)
        self._engine = engine
        return engine

    @staticmethod
    def _select_voice(engine: Any) -> None:
        for voice in engine.getProperty("voices"):
            descriptor = f"{voice.id} {voice.name} {getattr(voice, 'languages', '')}".lower()
            if any(marker in descriptor for marker in ("uk", "ukrain", "ru", "russian")):
                engine.setProperty("voice", voice.id)
                return


class FallbackSpeaker:
    def __init__(self, primary: Speaker, fallback: Speaker | None) -> None:
        self._primary = primary
        self._fallback = fallback

    def speak(self, text: str) -> None:
        try:
            self._primary.speak(text)
            return
        except (SpeechSynthesisError, AudioDeviceError) as error:
            if self._fallback is None:
                raise
            logger.warning("Основний TTS недоступний (%s) — використовую офлайн-голос", error)
        self._fallback.speak(text)


class SpeechService:
    def __init__(
        self,
        bus: EventBus,
        speaker: Speaker,
        settings: TtsSection,
        warmup: EdgeTtsSpeaker | None = None,
    ) -> None:
        self._bus = bus
        self._speaker = speaker
        self._settings = settings
        self._warmup = warmup
        self._queue: queue.Queue[object] = queue.Queue()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._bus.subscribe(SpeakRequested, self._on_speak)
        self._bus.subscribe(ShutdownRequested, lambda _: self.stop())
        self._thread = threading.Thread(target=self._run, name="tts", daemon=True)
        self._thread.start()
        if self._warmup is not None and self._settings.enabled:
            threading.Thread(target=self._warm_cache, name="tts-warmup", daemon=True).start()

    def stop(self) -> None:
        self._queue.put(_STOP)

    def _on_speak(self, event: SpeakRequested) -> None:
        if self._settings.enabled and event.text.strip():
            self._queue.put(event.text)

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is _STOP:
                return
            if isinstance(item, str):
                self._say(item)

    def _say(self, text: str) -> None:
        self._bus.dispatch_now(SpeechStarted(text))
        self._bus.publish(AssistantStateChanged(AssistantState.SPEAKING))
        try:
            self._speaker.speak(text)
        except (SpeechSynthesisError, AudioDeviceError) as error:
            logger.error("Не вдалося озвучити «%s»: %s", text, error)
        finally:
            self._bus.dispatch_now(SpeechFinished(text))
            self._bus.publish(AssistantStateChanged(AssistantState.IDLE))

    def _warm_cache(self) -> None:
        if self._warmup is None:
            return
        for phrase in COMMON_PHRASES:
            try:
                self._warmup.synthesize(phrase)
            except SpeechSynthesisError as error:
                logger.info("Кеш TTS не прогріто: %s", error)
                return
