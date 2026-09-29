from __future__ import annotations

from datetime import date, datetime

MONTHS_GENITIVE: tuple[str, ...] = (
    "січня", "лютого", "березня", "квітня", "травня", "червня",
    "липня", "серпня", "вересня", "жовтня", "листопада", "грудня",
)
WEEKDAYS: tuple[str, ...] = ("понеділок", "вівторок", "середа", "четвер", "п'ятниця", "субота", "неділя")


def plural(count: int, one: str, few: str, many: str) -> str:
    remainder_100 = count % 100
    remainder_10 = count % 10
    if 11 <= remainder_100 <= 14:
        return many
    if remainder_10 == 1:
        return one
    if 2 <= remainder_10 <= 4:
        return few
    return many


def format_duration(total_seconds: int) -> str:
    total = max(0, int(total_seconds))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours} {plural(hours, 'година', 'години', 'годин')}")
    if minutes:
        parts.append(f"{minutes} {plural(minutes, 'хвилина', 'хвилини', 'хвилин')}")
    if seconds or not parts:
        parts.append(f"{seconds} {plural(seconds, 'секунда', 'секунди', 'секунд')}")
    return " ".join(parts)


def format_duration_accusative(total_seconds: int) -> str:
    return (
        format_duration(total_seconds)
        .replace("година", "годину")
        .replace("хвилина", "хвилину")
        .replace("секунда", "секунду")
    )


def format_date(value: date) -> str:
    return f"{value.day} {MONTHS_GENITIVE[value.month - 1]} {value.year} року"


def format_time(value: datetime) -> str:
    return value.strftime("%H:%M")


def format_moment(value: datetime, now: datetime) -> str:
    delta_days = (value.date() - now.date()).days
    if delta_days == 0:
        return f"сьогодні о {format_time(value)}"
    if delta_days == 1:
        return f"завтра о {format_time(value)}"
    if delta_days == 2:
        return f"післязавтра о {format_time(value)}"
    return f"{value.day} {MONTHS_GENITIVE[value.month - 1]} о {format_time(value)}"
