from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from jarvis.core.intent import Intent

_NUMBER = re.compile(r"^\d+$")


@dataclass(frozen=True)
class PreparedText:
    raw: str
    core: str
    tokens: tuple[str, ...]

    @property
    def head(self) -> str:
        return self.tokens[0] if self.tokens else ""

    @property
    def tail(self) -> tuple[str, ...]:
        return self.tokens[1:]

    def contains(self, phrases: Iterable[str]) -> bool:
        padded = f" {self.core} "
        return any(f" {phrase} " in padded for phrase in phrases)

    def raw_contains(self, phrases: Iterable[str]) -> bool:
        padded = f" {self.raw} "
        return any(f" {phrase} " in padded for phrase in phrases)

    def equals(self, phrases: Iterable[str]) -> bool:
        options = set(phrases)
        return self.core in options or self.raw in options

    def has_stem(self, stems: Iterable[str]) -> bool:
        stems = tuple(stems)
        return any(token.startswith(stems) for token in self.tokens)

    def has_token(self, words: Iterable[str]) -> bool:
        options = set(words)
        return any(token in options for token in self.tokens)

    def first_number(self) -> int | None:
        for token in self.tokens:
            if _NUMBER.match(token):
                return int(token)
        return None

    def after(self, phrase: str) -> str:
        padded = f" {self.core} "
        marker = f" {phrase} "
        index = padded.find(marker)
        if index < 0:
            return ""
        return padded[index + len(marker) :].strip()

    def without(self, words: Iterable[str]) -> list[str]:
        options = set(words)
        return [token for token in self.tokens if token not in options]


Rule = Callable[[PreparedText], Intent | None]
