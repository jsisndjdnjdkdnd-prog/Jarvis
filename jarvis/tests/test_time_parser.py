from __future__ import annotations

from datetime import datetime

import pytest

from jarvis.nlu.durations import DurationParser
from jarvis.nlu.numbers import NumberWordsConverter
from jarvis.nlu.time_parser import NaturalTimeParser


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("двадцять п'ять", "25"),
        ("сто двадцять три", "123"),
        ("п'ять хвилин", "5 хвилин"),
        ("одна година", "1 година"),
        ("тридцять п'ять і десять", "35 і 10"),
        ("десять п'ять", "10 5"),
    ],
)
def test_number_words(text: str, expected: str) -> None:
    assert NumberWordsConverter().convert(text) == expected


@pytest.mark.parametrize(
    ("text", "seconds"),
    [
        ("5 хвилин", 300),
        ("півгодини", 1800),
        ("пів години", 1800),
        ("півтори хвилини", 90),
        ("2 години 15 хвилин", 8100),
        ("годину", 3600),
        ("3 дні", 259200),
    ],
)
def test_durations(text: str, seconds: int) -> None:
    assert DurationParser().parse(text) == seconds


@pytest.mark.parametrize(
    ("text", "when", "remainder"),
    [
        ("завтра о 9 подзвонити мамі", datetime(2026, 9, 30, 9, 0), "подзвонити мамі"),
        ("через пів години випити чай", datetime(2026, 9, 29, 14, 30), "випити чай"),
        ("о 18:30 зустріч", datetime(2026, 9, 29, 18, 30), "зустріч"),
        ("о пів на восьму вечора кіно", datetime(2026, 9, 29, 19, 30), "кіно"),
        ("о 5 забрати посилку", datetime(2026, 9, 29, 17, 0), "забрати посилку"),
        ("о 11 ранку дзвінок", datetime(2026, 9, 30, 11, 0), "дзвінок"),
        ("в понеділок о 10 30 звіт", datetime(2026, 10, 5, 10, 30), "звіт"),
        ("післязавтра купити хліб", datetime(2026, 10, 1, 9, 0), "купити хліб"),
        ("ввечері полити квіти", datetime(2026, 9, 29, 19, 0), "полити квіти"),
        ("о дев'ятій вечора вимкнути світло", datetime(2026, 9, 29, 21, 0), "вимкнути світло"),
    ],
)
def test_natural_time(time_parser: NaturalTimeParser, text: str, when: datetime, remainder: str) -> None:
    extraction = time_parser.extract(text)
    assert extraction is not None
    assert extraction.when == when
    assert extraction.remainder == remainder


def test_no_time_returns_none(time_parser: NaturalTimeParser) -> None:
    assert time_parser.extract("подзвонити мамі") is None
