from __future__ import annotations

import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from jarvis.nlu.durations import DurationParser
from jarvis.nlu.numbers import HOUR_ORDINALS, NumberWordsConverter

logger = logging.getLogger(__name__)

RELATIVE_MARKERS: frozenset[str] = frozenset({"через", "in", "спустя"})
TIME_PREPOSITIONS: frozenset[str] = frozenset({"о", "об", "в", "во", "at", "на", "у"})
HOUR_WORDS: frozenset[str] = frozenset({"годині", "година", "годину", "часов", "часа", "час", "o'clock", "год"})
MINUTE_WORDS: frozenset[str] = frozenset({"хвилин", "хвилини", "хвилина", "хв", "минут", "минуты", "minutes"})

DAY_OFFSETS: dict[str, int] = {
    "сьогодні": 0, "сегодня": 0, "today": 0,
    "завтра": 1, "tomorrow": 1,
    "післязавтра": 2, "послезавтра": 2,
}

WEEKDAYS: dict[str, int] = {
    "понеділок": 0, "понеділка": 0, "понедельник": 0, "monday": 0,
    "вівторок": 1, "вівторка": 1, "вторник": 1, "tuesday": 1,
    "середу": 2, "середа": 2, "среду": 2, "среда": 2, "wednesday": 2,
    "четвер": 3, "четверга": 3, "четверг": 3, "thursday": 3,
    "п'ятницю": 4, "п'ятниця": 4, "пятницу": 4, "пятница": 4, "friday": 4,
    "суботу": 5, "субота": 5, "субботу": 5, "суббота": 5, "saturday": 5,
    "неділю": 6, "неділя": 6, "воскресенье": 6, "sunday": 6,
}

HALF_PAST_TARGETS: dict[str, int] = {
    "першу": 1, "другу": 2, "третю": 3, "четверту": 4, "п'яту": 5, "шосту": 6, "сьому": 7,
    "восьму": 8, "дев'яту": 9, "десяту": 10, "одинадцяту": 11, "дванадцяту": 12,
}

MORNING_WORDS: frozenset[str] = frozenset({"ранку", "вранці", "зранку", "утра", "утром", "am", "morning"})
DAYTIME_WORDS: frozenset[str] = frozenset({"дня", "вдень", "днем", "afternoon"})
EVENING_WORDS: frozenset[str] = frozenset({"вечора", "ввечері", "увечері", "вечером", "вечера", "pm", "evening"})
NIGHT_WORDS: frozenset[str] = frozenset({"ночі", "вночі", "уночі", "ночью", "ночи", "night"})
PERIOD_DEFAULT_HOURS: dict[str, int] = {"morning": 9, "day": 13, "evening": 19, "night": 23}
DAY_PREPOSITIONS: frozenset[str] = frozenset({"в", "у", "во", "on"})

_CLOCK = re.compile(r"^(\d{1,2})[:.](\d{2})$")
_NUMBER = re.compile(r"^\d{1,2}$")


@dataclass(frozen=True)
class TimeExtraction:
    when: datetime
    remainder: str


@dataclass(frozen=True)
class _ClockMatch:
    hour: int
    minute: int
    start: int
    end: int


@dataclass(frozen=True)
class _DayMatch:
    target: date
    start: int
    end: int


class NaturalTimeParser:
    def __init__(
        self,
        clock: Callable[[], datetime] = datetime.now,
        default_hour: int = 9,
        numbers: NumberWordsConverter | None = None,
        durations: DurationParser | None = None,
        use_dateparser: bool = True,
    ) -> None:
        self._clock = clock
        self._default_hour = default_hour
        self._numbers = numbers or NumberWordsConverter()
        self._durations = durations or DurationParser(self._numbers)
        self._use_dateparser = use_dateparser

    def extract(self, text: str, prefer_afternoon: bool = True) -> TimeExtraction | None:
        tokens = self._numbers.convert(text).split()
        now = self._clock()
        relative = self._extract_relative(tokens, now)
        if relative is not None:
            return relative
        absolute = self._extract_absolute(tokens, now, prefer_afternoon)
        if absolute is not None:
            return absolute
        return self._extract_with_dateparser(text, now)

    def _extract_relative(self, tokens: list[str], now: datetime) -> TimeExtraction | None:
        for index, token in enumerate(tokens):
            if token not in RELATIVE_MARKERS:
                continue
            seconds, consumed = self._durations.parse_prefix(tokens, index + 1)
            if consumed == 0 or seconds <= 0:
                continue
            remainder = tokens[:index] + tokens[index + 1 + consumed :]
            return TimeExtraction(now + timedelta(seconds=seconds), " ".join(remainder))
        return None

    def _extract_absolute(
        self, tokens: list[str], now: datetime, prefer_afternoon: bool = True
    ) -> TimeExtraction | None:
        day = self._find_day(tokens, now)
        clock = self._find_clock(tokens)
        period, period_index = self._find_period(tokens)
        if day is None and clock is None and period is None:
            return None
        used: set[int] = set()
        if day is not None:
            used.update(range(day.start, day.end))
        if clock is not None:
            used.update(range(clock.start, clock.end))
        if period_index is not None:
            used.add(period_index)
        target_time = self._resolve_time(clock, period)
        when = self._combine(
            day,
            target_time,
            now,
            explicit_time=clock is not None or period is not None,
            allow_afternoon_shift=prefer_afternoon and clock is not None and period is None,
        )
        remainder = [token for index, token in enumerate(tokens) if index not in used]
        return TimeExtraction(when, " ".join(remainder))

    @staticmethod
    def _combine(
        day: _DayMatch | None,
        target_time: time,
        now: datetime,
        explicit_time: bool,
        allow_afternoon_shift: bool,
    ) -> datetime:
        if day is not None:
            return datetime.combine(day.target, target_time)
        candidate = datetime.combine(now.date(), target_time)
        if not explicit_time or candidate > now:
            return candidate
        afternoon = candidate + timedelta(hours=12)
        if allow_afternoon_shift and target_time.hour < 12 and afternoon > now:
            return afternoon
        return candidate + timedelta(days=1)

    def _resolve_time(self, clock: _ClockMatch | None, period: str | None) -> time:
        if clock is None:
            hour = PERIOD_DEFAULT_HOURS.get(period or "", self._default_hour)
            return time(hour=hour)
        hour = self._apply_period(clock.hour, period)
        return time(hour=hour % 24, minute=clock.minute)

    @staticmethod
    def _apply_period(hour: int, period: str | None) -> int:
        if period in {"evening", "day"} and hour < 12:
            return hour + 12
        if period == "night" and hour == 12:
            return 0
        if period == "night" and 6 <= hour < 12:
            return hour + 12
        if period == "morning" and hour == 12:
            return 0
        return hour

    def _find_day(self, tokens: Sequence[str], now: datetime) -> _DayMatch | None:
        for index, token in enumerate(tokens):
            if token in DAY_OFFSETS:
                target = now.date() + timedelta(days=DAY_OFFSETS[token])
                return _DayMatch(target, index, index + 1)
            if token in WEEKDAYS:
                start = index - 1 if index > 0 and tokens[index - 1] in DAY_PREPOSITIONS else index
                return _DayMatch(self._next_weekday(now.date(), WEEKDAYS[token]), start, index + 1)
        return None

    @staticmethod
    def _next_weekday(today: date, weekday: int) -> date:
        delta = (weekday - today.weekday()) % 7
        return today + timedelta(days=delta or 7)

    def _find_clock(self, tokens: Sequence[str]) -> _ClockMatch | None:
        for index, token in enumerate(tokens):
            match = self._clock_at(tokens, index)
            if match is not None:
                return match
            clock = _CLOCK.match(token)
            if clock is not None and self._valid(int(clock.group(1)), int(clock.group(2))):
                return _ClockMatch(int(clock.group(1)), int(clock.group(2)), index, index + 1)
        return None

    def _clock_at(self, tokens: Sequence[str], index: int) -> _ClockMatch | None:
        if tokens[index] not in TIME_PREPOSITIONS or index + 1 >= len(tokens):
            return None
        half_past = self._half_past(tokens, index + 1)
        if half_past is not None:
            return half_past
        return self._hour_minutes(tokens, index, index + 1)

    def _half_past(self, tokens: Sequence[str], index: int) -> _ClockMatch | None:
        if index + 2 >= len(tokens) or tokens[index] != "пів" or tokens[index + 1] != "на":
            return None
        target = HALF_PAST_TARGETS.get(tokens[index + 2])
        if target is None:
            return None
        return _ClockMatch((target - 1) % 12 or 12, 30, index - 1, index + 3)

    def _hour_minutes(self, tokens: Sequence[str], start: int, index: int) -> _ClockMatch | None:
        token = tokens[index]
        clock = _CLOCK.match(token)
        if clock is not None:
            hour, minute = int(clock.group(1)), int(clock.group(2))
            return _ClockMatch(hour, minute, start, index + 1) if self._valid(hour, minute) else None
        hour = self._hour_value(token)
        if hour is None:
            return None
        end = index + 1
        if end < len(tokens) and tokens[end] in HOUR_WORDS:
            end += 1
        minute = 0
        if end < len(tokens) and _NUMBER.match(tokens[end]) and int(tokens[end]) < 60:
            minute = int(tokens[end])
            end += 1
            if end < len(tokens) and tokens[end] in MINUTE_WORDS:
                end += 1
        return _ClockMatch(hour, minute, start, end) if self._valid(hour, minute) else None

    @staticmethod
    def _hour_value(token: str) -> int | None:
        if _NUMBER.match(token):
            return int(token)
        return HOUR_ORDINALS.get(token)

    @staticmethod
    def _find_period(tokens: Sequence[str]) -> tuple[str | None, int | None]:
        for index, token in enumerate(tokens):
            if token in MORNING_WORDS:
                return "morning", index
            if token in DAYTIME_WORDS:
                return "day", index
            if token in EVENING_WORDS:
                return "evening", index
            if token in NIGHT_WORDS:
                return "night", index
        return None, None

    @staticmethod
    def _valid(hour: int, minute: int) -> bool:
        return 0 <= hour <= 24 and 0 <= minute < 60

    def _extract_with_dateparser(self, text: str, now: datetime) -> TimeExtraction | None:
        if not self._use_dateparser:
            return None
        try:
            from dateparser.search import search_dates
        except ImportError:
            logger.warning("dateparser не встановлено — складні дати недоступні")
            return None
        found = search_dates(
            text,
            languages=["uk", "ru", "en"],
            settings={"PREFER_DATES_FROM": "future", "RELATIVE_BASE": now},
        )
        if not found:
            return None
        matched_text, moment = found[0]
        if moment <= now:
            return None
        remainder = text.replace(matched_text, " ")
        return TimeExtraction(moment.replace(tzinfo=None), " ".join(remainder.split()))
