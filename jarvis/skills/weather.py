from __future__ import annotations

import logging
import math
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Protocol

import httpx

from jarvis.core.config import LocationSection
from jarvis.core.context import DialogContext, SkillResult
from jarvis.core.errors import SkillError
from jarvis.core.intent import Intent, IntentName, WeatherPeriod

logger = logging.getLogger(__name__)

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
CURRENT_FIELDS = "temperature_2m,apparent_temperature,weather_code,wind_speed_10m,relative_humidity_2m"
DAILY_FIELDS = "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"
FORECAST_DAYS = 3
WEATHER_UNAVAILABLE = "Не вдалося отримати погоду, сер."

UMBRELLA_PROBABILITY = 50
COLD_TEMPERATURE = -5.0
HOT_TEMPERATURE = 30.0
STRONG_WIND = 12.0
NOTICEABLE_FEELS_LIKE_GAP = 2

WEATHER_DESCRIPTIONS: dict[int, str] = {
    0: "ясно",
    1: "переважно ясно",
    2: "мінлива хмарність",
    3: "хмарно",
    45: "туман",
    48: "туман з памороззю",
    51: "легка мряка",
    53: "мряка",
    55: "густа мряка",
    56: "легка крижана мряка",
    57: "густа крижана мряка",
    61: "невеликий дощ",
    63: "дощ",
    65: "сильний дощ",
    66: "крижаний дощ",
    67: "сильний крижаний дощ",
    71: "невеликий сніг",
    73: "сніг",
    75: "сильний сніг",
    77: "снігова крупа",
    80: "невелика злива",
    81: "злива",
    82: "сильна злива",
    85: "невеликий снігопад",
    86: "сильний снігопад",
    95: "гроза",
    96: "гроза з невеликим градом",
    99: "гроза з сильним градом",
}
WET_WEATHER_CODES: frozenset[int] = frozenset(
    {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99}
)
UNKNOWN_WEATHER = "мінлива погода"


@dataclass(frozen=True)
class Place:
    name: str
    latitude: float
    longitude: float


@dataclass(frozen=True)
class CurrentWeather:
    temperature: float
    apparent_temperature: float
    weather_code: int
    wind_speed: float
    humidity: float


@dataclass(frozen=True)
class DailyWeather:
    date: date
    weather_code: int
    temperature_max: float
    temperature_min: float
    precipitation_probability: int | None


@dataclass(frozen=True)
class Forecast:
    current: CurrentWeather
    days: tuple[DailyWeather, ...]


class WeatherProvider(Protocol):
    def geocode(self, city: str) -> Place: ...

    def forecast(self, place: Place) -> Forecast: ...


def describe_weather(code: int) -> str:
    return WEATHER_DESCRIPTIONS.get(code, UNKNOWN_WEATHER)


def is_wet(code: int) -> bool:
    return code in WET_WEATHER_CODES


def round_half_up(value: float) -> int:
    return math.floor(value + 0.5)


def format_temperature(value: float) -> str:
    rounded = round_half_up(value)
    if rounded > 0:
        return f"+{rounded}°"
    if rounded < 0:
        return f"-{abs(rounded)}°"
    return "0°"


class OpenMeteoClient:
    def __init__(self, timeout: float = 8.0, transport: httpx.BaseTransport | None = None) -> None:
        self._timeout = timeout
        self._transport = transport

    def geocode(self, city: str) -> Place:
        payload = self._get(GEOCODING_URL, {"name": city, "count": 1, "language": "uk", "format": "json"})
        results = payload.get("results") or []
        if not results:
            raise SkillError(f"Не знайшов місто «{city}», сер.")
        try:
            best = results[0]
            return Place(name=str(best["name"]), latitude=float(best["latitude"]), longitude=float(best["longitude"]))
        except (KeyError, TypeError, ValueError) as error:
            raise SkillError(WEATHER_UNAVAILABLE) from error

    def forecast(self, place: Place) -> Forecast:
        payload = self._get(
            FORECAST_URL,
            {
                "latitude": place.latitude,
                "longitude": place.longitude,
                "current": CURRENT_FIELDS,
                "daily": DAILY_FIELDS,
                "timezone": "auto",
                "forecast_days": FORECAST_DAYS,
                "wind_speed_unit": "ms",
            },
        )
        try:
            return Forecast(current=self._current(payload["current"]), days=self._days(payload["daily"]))
        except (KeyError, TypeError, ValueError, IndexError) as error:
            raise SkillError(WEATHER_UNAVAILABLE) from error

    def _get(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
                response = client.get(url, params=params)
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            logger.warning("Open-Meteo недоступний: %s", error)
            raise SkillError(WEATHER_UNAVAILABLE) from error
        if not isinstance(payload, dict):
            raise SkillError(WEATHER_UNAVAILABLE)
        return payload

    @staticmethod
    def _current(section: dict[str, Any]) -> CurrentWeather:
        return CurrentWeather(
            temperature=float(section["temperature_2m"]),
            apparent_temperature=float(section["apparent_temperature"]),
            weather_code=int(section["weather_code"]),
            wind_speed=float(section["wind_speed_10m"]),
            humidity=float(section["relative_humidity_2m"]),
        )

    @staticmethod
    def _days(section: dict[str, Any]) -> tuple[DailyWeather, ...]:
        dates: Sequence[str] = section["time"]
        probabilities: Sequence[Any] = section.get("precipitation_probability_max") or [None] * len(dates)
        return tuple(
            DailyWeather(
                date=date.fromisoformat(dates[index]),
                weather_code=int(section["weather_code"][index]),
                temperature_max=float(section["temperature_2m_max"][index]),
                temperature_min=float(section["temperature_2m_min"][index]),
                precipitation_probability=None if probabilities[index] is None else int(probabilities[index]),
            )
            for index in range(len(dates))
        )


@dataclass(frozen=True)
class _CachedForecast:
    fetched_at: datetime
    forecast: Forecast


class WeatherSkill:
    name = "weather"
    intents = frozenset({IntentName.WEATHER})

    def __init__(
        self,
        provider: WeatherProvider,
        location: LocationSection,
        clock: Callable[[], datetime] = datetime.now,
        cache_seconds: float = 600,
    ) -> None:
        self._provider = provider
        self._location = location
        self._clock = clock
        self._cache_seconds = cache_seconds
        self._places: dict[str, Place] = {}
        self._forecasts: dict[Place, _CachedForecast] = {}
        self._lock = threading.Lock()

    def handle(self, intent: Intent, context: DialogContext) -> SkillResult:
        place = self._place(intent.target)
        forecast = self._forecast(place)
        period = self._period(intent.mode)
        if period is WeatherPeriod.NOW:
            return SkillResult(self._describe_now(place, forecast), learnable=False)
        return SkillResult(self._describe_day(place, forecast, period), learnable=False)

    @staticmethod
    def _period(mode: str | None) -> WeatherPeriod:
        try:
            return WeatherPeriod(mode) if mode else WeatherPeriod.NOW
        except ValueError:
            return WeatherPeriod.NOW

    def _place(self, target: str | None) -> Place:
        city = " ".join((target or "").split())
        location = self._location
        if not city and location.latitude is not None and location.longitude is not None:
            return Place(name=location.city, latitude=location.latitude, longitude=location.longitude)
        name = city or location.city
        key = name.casefold()
        with self._lock:
            known = self._places.get(key)
        if known is not None:
            return known
        place = self._provider.geocode(name)
        with self._lock:
            self._places[key] = place
        return place

    def _forecast(self, place: Place) -> Forecast:
        now = self._clock()
        with self._lock:
            cached = self._forecasts.get(place)
        if cached is not None and (now - cached.fetched_at).total_seconds() < self._cache_seconds:
            return cached.forecast
        forecast = self._provider.forecast(place)
        with self._lock:
            self._forecasts[place] = _CachedForecast(fetched_at=now, forecast=forecast)
        return forecast

    def _describe_now(self, place: Place, forecast: Forecast) -> str:
        current = forecast.current
        parts = [f"зараз {format_temperature(current.temperature)}", describe_weather(current.weather_code)]
        feels_gap = abs(round_half_up(current.apparent_temperature) - round_half_up(current.temperature))
        if feels_gap >= NOTICEABLE_FEELS_LIKE_GAP:
            parts.append(f"відчувається як {format_temperature(current.apparent_temperature)}")
        parts.append(f"вітер {round_half_up(current.wind_speed)} м/с")
        today = self._day(forecast, self._clock().date())
        probability = today.precipitation_probability if today is not None else None
        advice = self._advice(
            coldest=min(current.temperature, current.apparent_temperature),
            warmest=current.temperature,
            wet=is_wet(current.weather_code) or (probability or 0) >= UMBRELLA_PROBABILITY,
            wind=current.wind_speed,
        )
        return self._sentence(f"{place.name}: {', '.join(parts)}.", advice)

    def _describe_day(self, place: Place, forecast: Forecast, period: WeatherPeriod) -> str:
        offset = 1 if period is WeatherPeriod.TOMORROW else 0
        label = "Завтра" if offset else "Сьогодні"
        day = self._day(forecast, self._clock().date() + timedelta(days=offset), fallback_index=offset)
        if day is None:
            raise SkillError(f"Прогнозу на {label.lower()} поки немає, сер.")
        parts = [
            f"від {format_temperature(day.temperature_min)} до {format_temperature(day.temperature_max)}",
            describe_weather(day.weather_code),
        ]
        if day.precipitation_probability is not None:
            parts.append(f"ймовірність опадів {day.precipitation_probability}%")
        advice = self._advice(
            coldest=day.temperature_min,
            warmest=day.temperature_max,
            wet=(day.precipitation_probability or 0) >= UMBRELLA_PROBABILITY,
            wind=0.0,
        )
        return self._sentence(f"{label}, {place.name}: {', '.join(parts)}.", advice)

    @staticmethod
    def _day(forecast: Forecast, wanted: date, fallback_index: int = 0) -> DailyWeather | None:
        for day in forecast.days:
            if day.date == wanted:
                return day
        if 0 <= fallback_index < len(forecast.days):
            return forecast.days[fallback_index]
        return None

    @staticmethod
    def _advice(coldest: float, warmest: float, wet: bool, wind: float) -> list[str]:
        advice: list[str] = []
        if wet:
            advice.append("Раджу взяти парасольку, сер.")
        if coldest <= COLD_TEMPERATURE:
            advice.append("Одягніться тепліше.")
        elif warmest >= HOT_TEMPERATURE:
            advice.append("Спекотно, не забувайте про воду.")
        if wind >= STRONG_WIND:
            advice.append("Вітер сильний, тримайтеся подалі від дерев і рекламних щитів.")
        return advice

    @staticmethod
    def _sentence(summary: str, advice: list[str]) -> str:
        return " ".join([summary, *advice])
