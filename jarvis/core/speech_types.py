from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True)
class RecognizedWord:
    text: str
    start: float
    end: float
    confidence: float = 1.0


@dataclass(frozen=True)
class Transcript:
    text: str
    words: tuple[RecognizedWord, ...] = ()
    language: str = "uk"
    alternatives: tuple[str, ...] = ()

    @property
    def confidence(self) -> float:
        if not self.words:
            return 0.0 if not self.text else 1.0
        return sum(word.confidence for word in self.words) / len(self.words)

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()


@dataclass(frozen=True)
class Utterance:
    transcript: Transcript
    audio: bytes | None = None
    sample_rate: int = 16000


class CommandSource(StrEnum):
    VOICE = "voice"
    TEXT = "text"
    SYSTEM = "system"


class AssistantState(StrEnum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    EXECUTING = "executing"
    SPEAKING = "speaking"
    TRAINING = "training"
    PAUSED = "paused"
