from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from jarvis.core.speech_types import Transcript


@runtime_checkable
class Transcriber(Protocol):
    def transcribe(
        self,
        pcm: bytes,
        language: str | None = None,
        grammar: Sequence[str] | None = None,
        alternatives: int = 0,
    ) -> Transcript: ...

    def transcribe_command(self, pcm: bytes, grammar: Sequence[str] | None) -> Transcript: ...

    def is_reliable(self, transcript: Transcript) -> bool: ...
