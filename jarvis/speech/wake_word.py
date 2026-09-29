from __future__ import annotations

import threading
from collections.abc import Iterable
from dataclasses import dataclass

from rapidfuzz import fuzz

from jarvis.core.speech_types import RecognizedWord, Transcript
from jarvis.nlu.text_normalizer import TextNormalizer
from jarvis.nlu.transliteration import phonetic_key
from jarvis.speech.recognizer_vosk import UNKNOWN_TOKEN, StreamingRecognizer


@dataclass(frozen=True)
class WakeDetection:
    final: bool
    matched: bool = True
    tail_audio: bytes = b""
    tail_seconds: float = 0.0
    tail_word_count: int = 0


class WakeWordMatcher:
    def __init__(self, wake_words: Iterable[str], threshold: float) -> None:
        self._threshold = threshold
        self._lock = threading.Lock()
        self._base = tuple(TextNormalizer.basic(word) for word in wake_words)
        self._variants: tuple[str, ...] = self._base

    @property
    def variants(self) -> tuple[str, ...]:
        with self._lock:
            return self._variants

    def update_learned(self, learned: Iterable[str]) -> None:
        combined = dict.fromkeys([*self._base, *(TextNormalizer.basic(item) for item in learned)])
        with self._lock:
            self._variants = tuple(item for item in combined if item)

    def matches(self, token: str) -> bool:
        if UNKNOWN_TOKEN in token:
            return False
        normalized = TextNormalizer.basic(token)
        if not normalized:
            return False
        key = phonetic_key(normalized)
        for variant in self.variants:
            if normalized == variant:
                return True
            if fuzz.ratio(key, phonetic_key(variant)) >= self._threshold:
                return True
        return False

    def find_in_text(self, text: str) -> int | None:
        tokens = text.split()
        for size in (1, 2):
            for index in range(len(tokens) - size + 1):
                if self.matches(" ".join(tokens[index : index + size]).replace(" ", "")):
                    return index + size - 1
        return None

    def find_in_words(self, words: Iterable[RecognizedWord]) -> RecognizedWord | None:
        items = list(words)
        for index, word in enumerate(items):
            if self.matches(word.text):
                return word
            if index + 1 < len(items) and self.matches(word.text + items[index + 1].text):
                return items[index + 1]
        return None


class WakeWordDetector:
    def __init__(
        self,
        recognizer: StreamingRecognizer,
        matcher: WakeWordMatcher,
        sample_rate: int,
    ) -> None:
        self._recognizer = recognizer
        self._matcher = matcher
        self._sample_rate = sample_rate
        self._buffer = bytearray()
        self._announced = False

    def reset(self) -> None:
        self._recognizer.reset()
        self._buffer = bytearray()
        self._announced = False

    def feed(self, chunk: bytes) -> WakeDetection | None:
        self._buffer.extend(chunk)
        transcript = self._recognizer.accept(chunk)
        if transcript is not None:
            return self._on_final(transcript)
        if self._announced:
            return None
        if self._matcher.find_in_text(self._recognizer.partial()) is None:
            return None
        self._announced = True
        return WakeDetection(final=False)

    def _on_final(self, transcript: Transcript) -> WakeDetection | None:
        audio = bytes(self._buffer)
        was_announced = self._announced
        self.reset()
        wake = self._matcher.find_in_words(transcript.words)
        if wake is None:
            return WakeDetection(final=True, matched=False) if was_announced else None
        start = min(len(audio), int(wake.end * self._sample_rate) * 2)
        tail = audio[start:]
        return WakeDetection(
            final=True,
            tail_audio=tail,
            tail_seconds=len(tail) / (2 * self._sample_rate),
            tail_word_count=sum(1 for word in transcript.words if word.start >= wake.end),
        )
