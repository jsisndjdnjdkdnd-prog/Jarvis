from __future__ import annotations

import re
from collections.abc import Sequence

from jarvis.nlu.numbers import NumberWordsConverter

SECOND = 1
MINUTE = 60
HOUR = 3600
DAY = 86400
WEEK = 604800

HALF_WORDS: frozenset[str] = frozenset({"пів", "пол", "half"})
ONE_AND_HALF_WORDS: frozenset[str] = frozenset({"півтори", "полтора", "полторы"})
JOINERS: frozenset[str] = frozenset({"і", "та", "й", "и", "and"})
DAY_WORDS: frozenset[str] = frozenset({"день", "дні", "днів", "дня", "дней", "днями", "day", "days", "добу", "доби"})
HOUR_EXACT: frozenset[str] = frozenset({"год", "час", "часа", "часов", "h"})
_NUMBER = re.compile(r"^\d+(?:[.,]\d+)?$")
_COMPOUND_HALF = re.compile(r"^(пів|пол)(.+)$")


def unit_seconds(token: str) -> int | None:
    if token.startswith(("сек", "second")):
        return SECOND
    if token.startswith(("хв", "хвилин", "минут", "minute")) or token in {"min", "мин"}:
        return MINUTE
    if token.startswith(("годин", "hour")) or token in HOUR_EXACT:
        return HOUR
    if token in DAY_WORDS:
        return DAY
    if token.startswith(("тиж", "недел", "week")):
        return WEEK
    return None


class DurationParser:
    def __init__(self, numbers: NumberWordsConverter | None = None) -> None:
        self._numbers = numbers or NumberWordsConverter()

    def parse(self, text: str) -> int | None:
        tokens = self._numbers.convert(text).split()
        for start in range(len(tokens)):
            seconds, consumed = self.parse_prefix(tokens, start)
            if consumed and seconds > 0:
                return seconds
        return None

    def find(self, tokens: Sequence[str]) -> tuple[int, int, int] | None:
        for start in range(len(tokens)):
            seconds, consumed = self.parse_prefix(tokens, start)
            if consumed and seconds > 0:
                return seconds, start, consumed
        return None

    def parse_prefix(self, tokens: Sequence[str], start: int) -> tuple[int, int]:
        total = 0.0
        index = start
        while index < len(tokens):
            step = self._parse_component(tokens, index)
            if step is None:
                break
            seconds, consumed = step
            total += seconds
            index += consumed
            if self._has_joined_component(tokens, index):
                index += 1
        if index > start and tokens[index - 1] in JOINERS:
            index -= 1
        return int(round(total)), index - start

    def _has_joined_component(self, tokens: Sequence[str], index: int) -> bool:
        if index >= len(tokens) or tokens[index] not in JOINERS:
            return False
        return self._parse_component(tokens, index + 1) is not None

    def _parse_component(self, tokens: Sequence[str], index: int) -> tuple[float, int] | None:
        token = tokens[index]
        compound = self._compound_half(token)
        if compound is not None:
            return compound, 1
        multiplier, offset = self._multiplier(token)
        unit_index = index + offset
        if unit_index >= len(tokens):
            return None
        unit = unit_seconds(tokens[unit_index])
        if unit is None:
            return None
        return multiplier * unit, offset + 1

    @staticmethod
    def _multiplier(token: str) -> tuple[float, int]:
        if token in HALF_WORDS:
            return 0.5, 1
        if token in ONE_AND_HALF_WORDS:
            return 1.5, 1
        if _NUMBER.match(token):
            return float(token.replace(",", ".")), 1
        return 1.0, 0

    @staticmethod
    def _compound_half(token: str) -> float | None:
        match = _COMPOUND_HALF.match(token)
        if match is None:
            return None
        unit = unit_seconds(match.group(2))
        if unit is None:
            return None
        return 0.5 * unit
