from __future__ import annotations

import re
from collections.abc import Iterable

_APOSTROPHES = str.maketrans({"’": "'", "ʼ": "'", "`": "'", "´": "'", "‘": "'", "ё": "е"})
_NON_WORD = re.compile(r"[^\w'\s:.]+", re.UNICODE)
_LOOSE_PUNCTUATION = re.compile(r"(?<!\d)[.:]|[.:](?!\d)")
_SPACES = re.compile(r"\s+")

DEFAULT_FILLERS: tuple[str, ...] = (
    "будь ласка",
    "будь-ласка",
    "пожалуйста",
    "please",
    "будь ласочка",
)


class TextNormalizer:
    def __init__(
        self,
        wake_words: Iterable[str] = (),
        fillers: Iterable[str] = DEFAULT_FILLERS,
    ) -> None:
        self._wake_words = tuple(sorted({self.basic(word) for word in wake_words}, key=len, reverse=True))
        self._fillers = tuple(sorted({self.basic(filler) for filler in fillers}, key=len, reverse=True))

    @staticmethod
    def basic(text: str) -> str:
        lowered = text.lower().translate(_APOSTROPHES).replace("-", " ")
        cleaned = _NON_WORD.sub(" ", lowered)
        cleaned = _LOOSE_PUNCTUATION.sub(" ", cleaned)
        return _SPACES.sub(" ", cleaned).strip(" '")

    def normalize(self, text: str) -> str:
        normalized = self.basic(text)
        normalized = self.strip_wake_word(normalized)
        return self._remove_fillers(normalized)

    def strip_wake_word(self, text: str) -> str:
        for wake_word in self._wake_words:
            if text == wake_word:
                return ""
            if text.startswith(wake_word + " "):
                return text[len(wake_word) + 1 :].strip()
        return text

    def _remove_fillers(self, text: str) -> str:
        padded = f" {text} "
        for filler in self._fillers:
            padded = padded.replace(f" {filler} ", " ")
        return _SPACES.sub(" ", padded).strip()
