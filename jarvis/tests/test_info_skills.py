from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import quote_plus

import httpx
import pytest

from jarvis.core.config import LocationSection
from jarvis.core.context import DialogContext
from jarvis.core.errors import ActionExecutionError, MusicError, SkillError
from jarvis.core.intent import Intent, IntentName, SystemInfoKind, WeatherPeriod
from jarvis.skills.calculator import CalculatorSkill, ExpressionTranslator, SafeCalculator, format_number
from jarvis.skills.system_info import (
    BatteryStatus,
    DiskStatus,
    MemoryStatus,
    PsutilProbe,
    SystemInfoSkill,
    format_uptime,
)
from jarvis.skills.weather import (
    WEATHER_DESCRIPTIONS,
    CurrentWeather,
    DailyWeather,
    Forecast,
    OpenMeteoClient,
    Place,
    WeatherSkill,
    describe_weather,
    format_temperature,
)
from jarvis.skills.web_search import WebSearchSkill
from jarvis.skills.youtube import VideoResult, YouTubePlaySkill, YtDlpYouTubeSearch

NOW = datetime(2026, 9, 29, 14, 0)
KYIV = Place(name="Київ", latitude=50.45, longitude=30.52)


class FakeOpener:
    def __init__(self, fail: bool = False) -> None:
        self.opened: list[str] = []
        self._fail = fail

    def open(self, target: str) -> None:
        if self._fail:
            raise ActionExecutionError("браузер недоступний")
        self.opened.append(target)


class FakeYouTubeSearch:
    def __init__(self, results: list[VideoResult] | None = None, error: MusicError | None = None) -> None:
        self._results = results or []
        self._error = error
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, limit: int) -> list[VideoResult]:
        self.calls.append((query, limit))
        if self._error is not None:
            raise self._error
        return self._results


class FakeYtDlpClient:
    def __init__(self, info: dict[str, Any]) -> None:
        self._info = info
        self.calls: list[tuple[str, bool]] = []

    def extract(self, target: str, full: bool) -> dict[str, Any]:
        self.calls.append((target, full))
        return self._info


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


@dataclass
class FakeWeatherProvider:
    forecast_value: Forecast
    places: dict[str, Place] = field(default_factory=dict)
    geocoded: list[str] = field(default_factory=list)
    forecasted: list[Place] = field(default_factory=list)

    def geocode(self, city: str) -> Place:
        self.geocoded.append(city)
        if city not in self.places:
            raise SkillError(f"Не знайшов місто «{city}», сер.")
        return self.places[city]

    def forecast(self, place: Place) -> Forecast:
        self.forecasted.append(place)
        return self.forecast_value


@dataclass
class FakeProbe:
    battery_status: BatteryStatus | None = None
    cpu: float = 14.2
    memory_status: MemoryStatus = field(default_factory=lambda: MemoryStatus(60.2, 9.6, 15.9))
    disk_status: DiskStatus = field(default_factory=lambda: DiskStatus(71.6, 120.4))
    booted_at: datetime = NOW - timedelta(hours=3, minutes=12)

    def battery(self) -> BatteryStatus | None:
        return self.battery_status

    def cpu_percent(self) -> float:
        return self.cpu

    def memory(self) -> MemoryStatus:
        return self.memory_status

    def disk(self) -> DiskStatus:
        return self.disk_status

    def boot_time(self) -> datetime:
        return self.booted_at


def make_forecast(
    temperature: float = 12.3,
    apparent: float = 10.1,
    code: int = 3,
    wind: float = 4.2,
    tomorrow_probability: int | None = 60,
    today_probability: int | None = 10,
) -> Forecast:
    return Forecast(
        current=CurrentWeather(temperature, apparent, code, wind, 70.0),
        days=(
            DailyWeather(date(2026, 9, 29), 3, 14.4, 7.6, today_probability),
            DailyWeather(date(2026, 9, 30), 61, 15.2, 8.4, tomorrow_probability),
            DailyWeather(date(2026, 10, 1), 0, 16.0, 6.0, 0),
        ),
    )


@pytest.fixture
def context() -> DialogContext:
    return DialogContext()


def video(title: str, video_id: str) -> VideoResult:
    return VideoResult(title=title, url=f"https://www.youtube.com/watch?v={video_id}", channel="канал", duration_seconds=200)


def test_youtube_opens_best_result(context: DialogContext) -> None:
    opener = FakeOpener()
    search = FakeYouTubeSearch([video("Lo-fi радіо", "abc"), video("Інше", "def")])
    result = YouTubePlaySkill(search, opener).handle(Intent(name=IntentName.YOUTUBE_PLAY, query="лофі"), context)
    assert opener.opened == ["https://www.youtube.com/watch?v=abc"]
    assert result.reply == "Вмикаю «Lo-fi радіо» на YouTube."
    assert result.success and not result.learnable
    assert search.calls == [("лофі", 5)]


def test_youtube_without_query_opens_home(context: DialogContext) -> None:
    opener = FakeOpener()
    search = FakeYouTubeSearch()
    result = YouTubePlaySkill(search, opener).handle(Intent(name=IntentName.YOUTUBE_PLAY, query="  "), context)
    assert opener.opened == ["https://www.youtube.com"]
    assert result.reply == "Відкриваю YouTube."
    assert search.calls == []


@pytest.mark.parametrize(
    "search",
    [FakeYouTubeSearch(error=MusicError("yt-dlp впав")), FakeYouTubeSearch(results=[])],
)
def test_youtube_falls_back_to_search_page(search: FakeYouTubeSearch, context: DialogContext) -> None:
    opener = FakeOpener()
    result = YouTubePlaySkill(search, opener).handle(
        Intent(name=IntentName.YOUTUBE_PLAY, query="котики & собаки"), context
    )
    assert opener.opened == [f"https://www.youtube.com/results?search_query={quote_plus('котики & собаки')}"]
    assert result.reply == "Відкрив пошук на YouTube."
    assert not result.learnable


def test_youtube_shortens_long_titles(context: DialogContext) -> None:
    title = "Дуже довга назва відео " * 10
    result = YouTubePlaySkill(FakeYouTubeSearch([video(title, "x")]), FakeOpener()).handle(
        Intent(name=IntentName.YOUTUBE_PLAY, query="назва"), context
    )
    spoken = result.reply.removeprefix("Вмикаю «").removesuffix("» на YouTube.")
    assert spoken.endswith("…")
    assert len(spoken) <= 81


def test_youtube_reports_browser_failure(context: DialogContext) -> None:
    result = YouTubePlaySkill(FakeYouTubeSearch([video("A", "a")]), FakeOpener(fail=True)).handle(
        Intent(name=IntentName.YOUTUBE_PLAY, query="a"), context
    )
    assert not result.success
    assert result.reply == "Не вдалося відкрити браузер, сер."


def test_ytdlp_youtube_search_builds_watch_urls() -> None:
    client = FakeYtDlpClient(
        {
            "entries": [
                {"id": "aaa", "url": "https://www.youtube.com/watch?v=aaa", "title": "Перше", "channel": "К1", "duration": 61},
                {"id": "bbb", "url": "bbb", "title": "Друге", "uploader": "К2", "duration": None},
                {"id": "ccc", "url": "https://www.youtube.com/shorts/ccc", "title": "Шорт"},
                None,
                {"title": "Без адреси"},
            ]
        }
    )
    results = YtDlpYouTubeSearch(client).search("джаз", 3)
    assert client.calls == [("ytsearch3:джаз", False)]
    assert [item.url for item in results] == [
        "https://www.youtube.com/watch?v=aaa",
        "https://www.youtube.com/watch?v=bbb",
        "https://www.youtube.com/watch?v=ccc",
    ]
    assert results[0] == VideoResult("Перше", "https://www.youtube.com/watch?v=aaa", "К1", 61.0)
    assert results[1].channel == "К2"
    assert results[1].duration_seconds is None


def test_ytdlp_youtube_search_handles_empty_info() -> None:
    assert YtDlpYouTubeSearch(FakeYtDlpClient({})).search("щось", 5) == []


def test_web_search_opens_google(context: DialogContext) -> None:
    opener = FakeOpener()
    result = WebSearchSkill(opener).handle(Intent(name=IntentName.WEB_SEARCH, query="рецепт борщу"), context)
    assert opener.opened == [f"https://www.google.com/search?q={quote_plus('рецепт борщу')}"]
    assert result.reply == "Шукаю «рецепт борщу» в Google."
    assert result.success and not result.learnable


def test_web_search_without_query_asks(context: DialogContext) -> None:
    opener = FakeOpener()
    result = WebSearchSkill(opener).handle(Intent(name=IntentName.WEB_SEARCH), context)
    assert result.reply == "Що саме знайти, сер?"
    assert not result.success and not result.learnable
    assert opener.opened == []


def weather_skill(
    provider: FakeWeatherProvider,
    clock: FakeClock | None = None,
    location: LocationSection | None = None,
) -> WeatherSkill:
    return WeatherSkill(provider, location or LocationSection(city="Київ"), clock=clock or FakeClock(NOW))


def test_weather_now_uses_default_city(context: DialogContext) -> None:
    provider = FakeWeatherProvider(make_forecast(), places={"Київ": KYIV})
    result = weather_skill(provider).handle(Intent(name=IntentName.WEATHER), context)
    assert result.reply == "Київ: зараз +12°, хмарно, відчувається як +10°, вітер 4 м/с."
    assert not result.learnable
    assert provider.geocoded == ["Київ"]


def test_weather_now_omits_similar_feels_like(context: DialogContext) -> None:
    provider = FakeWeatherProvider(make_forecast(temperature=0.2, apparent=-0.4, code=0), places={"Київ": KYIV})
    result = weather_skill(provider).handle(Intent(name=IntentName.WEATHER, mode=WeatherPeriod.NOW.value), context)
    assert result.reply == "Київ: зараз 0°, ясно, вітер 4 м/с."


def test_weather_tomorrow_with_umbrella_advice(context: DialogContext) -> None:
    provider = FakeWeatherProvider(make_forecast(), places={"Київ": KYIV})
    result = weather_skill(provider).handle(
        Intent(name=IntentName.WEATHER, mode=WeatherPeriod.TOMORROW.value), context
    )
    assert result.reply == (
        "Завтра, Київ: від +8° до +15°, невеликий дощ, ймовірність опадів 60%. Раджу взяти парасольку, сер."
    )


def test_weather_today_without_probability(context: DialogContext) -> None:
    provider = FakeWeatherProvider(make_forecast(today_probability=None), places={"Київ": KYIV})
    result = weather_skill(provider).handle(Intent(name=IntentName.WEATHER, mode="today"), context)
    assert result.reply == "Сьогодні, Київ: від +8° до +14°, хмарно."


def test_weather_cold_advice_and_rain_now(context: DialogContext) -> None:
    provider = FakeWeatherProvider(
        make_forecast(temperature=-6.6, apparent=-11.0, code=73, wind=13.0), places={"Київ": KYIV}
    )
    result = weather_skill(provider).handle(Intent(name=IntentName.WEATHER), context)
    assert result.reply.startswith("Київ: зараз -7°, сніг, відчувається як -11°, вітер 13 м/с.")
    assert "Одягніться тепліше." in result.reply
    assert "парасольку" not in result.reply
    assert "Вітер сильний" in result.reply


def test_weather_rain_now_suggests_umbrella(context: DialogContext) -> None:
    provider = FakeWeatherProvider(make_forecast(code=63), places={"Київ": KYIV})
    result = weather_skill(provider).handle(Intent(name=IntentName.WEATHER), context)
    assert result.reply.endswith("Раджу взяти парасольку, сер.")


def test_weather_for_named_city(context: DialogContext) -> None:
    lviv = Place("Львів", 49.84, 24.03)
    provider = FakeWeatherProvider(make_forecast(), places={"Львів": lviv})
    skill = weather_skill(provider)
    skill.handle(Intent(name=IntentName.WEATHER, target="Львів"), context)
    skill.handle(Intent(name=IntentName.WEATHER, target="Львів"), context)
    assert provider.geocoded == ["Львів"]
    assert provider.forecasted == [lviv]


def test_weather_skips_geocoding_with_configured_coordinates(context: DialogContext) -> None:
    provider = FakeWeatherProvider(make_forecast())
    location = LocationSection(city="Дім", latitude=50.0, longitude=30.0)
    result = weather_skill(provider, location=location).handle(Intent(name=IntentName.WEATHER), context)
    assert provider.geocoded == []
    assert provider.forecasted == [Place("Дім", 50.0, 30.0)]
    assert result.reply.startswith("Дім: зараз +12°")


def test_weather_caches_forecast_per_place(context: DialogContext) -> None:
    clock = FakeClock(NOW)
    provider = FakeWeatherProvider(make_forecast(), places={"Київ": KYIV})
    skill = weather_skill(provider, clock=clock)
    skill.handle(Intent(name=IntentName.WEATHER), context)
    clock.advance(599)
    skill.handle(Intent(name=IntentName.WEATHER, mode="tomorrow"), context)
    assert len(provider.forecasted) == 1
    clock.advance(2)
    skill.handle(Intent(name=IntentName.WEATHER), context)
    assert len(provider.forecasted) == 2


def test_weather_unknown_city_raises_polite_error(context: DialogContext) -> None:
    provider = FakeWeatherProvider(make_forecast())
    with pytest.raises(SkillError, match="Не знайшов місто «Атлантида», сер."):
        weather_skill(provider).handle(Intent(name=IntentName.WEATHER, target="Атлантида"), context)


def test_weather_invalid_mode_defaults_to_now(context: DialogContext) -> None:
    provider = FakeWeatherProvider(make_forecast(), places={"Київ": KYIV})
    result = weather_skill(provider).handle(Intent(name=IntentName.WEATHER, mode="вчора"), context)
    assert result.reply.startswith("Київ: зараз")


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0.0, "0°"), (-0.4, "0°"), (0.5, "+1°"), (3.4, "+3°"), (-2.6, "-3°"), (-12.0, "-12°"), (25.5, "+26°")],
)
def test_format_temperature(value: float, expected: str) -> None:
    assert format_temperature(value) == expected


def test_all_wmo_codes_have_descriptions() -> None:
    codes = [0, 1, 2, 3, 45, 48, 51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 71, 73, 75, 77, 80, 81, 82, 85, 86, 95, 96, 99]
    assert set(codes) == set(WEATHER_DESCRIPTIONS)
    assert describe_weather(95) == "гроза"
    assert describe_weather(12345) == "мінлива погода"


def open_meteo_transport(geocoding: dict[str, Any], forecast: dict[str, Any], seen: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "geocoding-api.open-meteo.com":
            return httpx.Response(200, json=geocoding)
        return httpx.Response(200, json=forecast)

    return httpx.MockTransport(handler)


FORECAST_PAYLOAD: dict[str, Any] = {
    "current": {
        "temperature_2m": 11.6,
        "apparent_temperature": 9.8,
        "weather_code": 2,
        "wind_speed_10m": 3.4,
        "relative_humidity_2m": 81,
    },
    "daily": {
        "time": ["2026-09-29", "2026-09-30"],
        "weather_code": [2, 61],
        "temperature_2m_max": [14.0, 15.0],
        "temperature_2m_min": [7.0, 8.0],
        "precipitation_probability_max": [5, None],
    },
}


def test_open_meteo_client_parses_responses() -> None:
    seen: list[httpx.Request] = []
    geocoding = {"results": [{"name": "Одеса", "latitude": 46.48, "longitude": 30.72}]}
    client = OpenMeteoClient(transport=open_meteo_transport(geocoding, FORECAST_PAYLOAD, seen))
    place = client.geocode("Одеса")
    forecast = client.forecast(place)
    assert place == Place("Одеса", 46.48, 30.72)
    assert forecast.current == CurrentWeather(11.6, 9.8, 2, 3.4, 81.0)
    assert forecast.days[1] == DailyWeather(date(2026, 9, 30), 61, 15.0, 8.0, None)
    geocoding_params = seen[0].url.params
    assert geocoding_params["name"] == "Одеса"
    assert geocoding_params["language"] == "uk"
    assert geocoding_params["count"] == "1"
    forecast_params = seen[1].url.params
    assert forecast_params["wind_speed_unit"] == "ms"
    assert forecast_params["timezone"] == "auto"
    assert forecast_params["forecast_days"] == "3"
    assert "precipitation_probability_max" in forecast_params["daily"]
    assert "relative_humidity_2m" in forecast_params["current"]


def test_open_meteo_client_reports_missing_city() -> None:
    client = OpenMeteoClient(transport=open_meteo_transport({"generationtime_ms": 0.1}, FORECAST_PAYLOAD, []))
    with pytest.raises(SkillError, match="Не знайшов місто «Нідевіль», сер."):
        client.geocode("Нідевіль")


def test_open_meteo_client_wraps_http_errors() -> None:
    client = OpenMeteoClient(transport=httpx.MockTransport(lambda request: httpx.Response(503)))
    with pytest.raises(SkillError, match="Не вдалося отримати погоду, сер."):
        client.forecast(KYIV)


def test_open_meteo_client_wraps_malformed_payload() -> None:
    broken = json.loads(json.dumps(FORECAST_PAYLOAD))
    del broken["current"]["weather_code"]
    client = OpenMeteoClient(transport=open_meteo_transport({}, broken, []))
    with pytest.raises(SkillError, match="Не вдалося отримати погоду, сер."):
        client.forecast(KYIV)


def test_open_meteo_client_wraps_network_errors() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    client = OpenMeteoClient(transport=httpx.MockTransport(refuse))
    with pytest.raises(SkillError, match="Не вдалося отримати погоду, сер."):
        client.geocode("Київ")


@pytest.fixture
def calculator() -> CalculatorSkill:
    return CalculatorSkill(ExpressionTranslator(), SafeCalculator())


@pytest.mark.parametrize(
    ("phrase", "reply"),
    [
        ("скільки буде двадцять п'ять помножити на чотири", "Це буде 100."),
        ("скільки буде 25 помножити на 4", "Це буде 100."),
        ("сто поділити на вісім", "Це буде 12,5."),
        ("корінь з шістдесят чотири", "Це буде 8."),
        ("квадратний корінь з 81", "Це буде 9."),
        ("п'ятнадцять відсотків від двохсот", "Це буде 30."),
        ("15 відсотків від 200", "Це буде 30."),
        ("два в квадраті плюс три", "Це буде 7."),
        ("три в кубі", "Це буде 27."),
        ("два в степені десять", "Це буде 1024."),
        ("два в третьому степені", "Це буде 8."),
        ("півтора помножити на чотири", "Це буде 6."),
        ("два кома п'ять плюс два кома п'ять", "Це буде 5."),
        ("нуль кома нуль п'ять помножити на сто", "Це буде 5."),
        ("два цілих п'ять десятих помножити на два", "Це буде 5."),
        ("дві тисячі шістсот двадцять мінус двадцять", "Це буде 2600."),
        ("дев'ятсот дев'яносто дев'ять плюс один", "Це буде 1000."),
        ("мільйон двісті тисяч поділити на сто", "Це буде 12000."),
        ("відніми три від десяти", "Це буде 7."),
        ("додай п'ять до десяти", "Це буде 15."),
        ("поділи дванадцять на чотири", "Це буде 3."),
        ("помнож три на чотири плюс два", "Це буде 14."),
        ("три на чотири", "Це буде 12."),
        ("три на мінус два", "Це буде мінус 6."),
        ("мінус п'ять плюс три", "Це буде мінус 2."),
        ("десять поділити на три", "Це буде 3,3333."),
        ("кубічний корінь з двадцяти семи", "Це буде 3."),
        ("сколько будет семь умножить на восемь", "Це буде 56."),
        ("посчитай сто разделить на четыре", "Це буде 25."),
        ("корень из сорока девяти", "Це буде 7."),
        ("what is five times six", "Це буде 30."),
        ("calculate twenty divided by four", "Це буде 5."),
        ("two hundred twenty plus five", "Це буде 225."),
        ("25 x 4", "Це буде 100."),
        ("Скільки буде 2,5 × 4?", "Це буде 10."),
        ("12:4", "Це буде 3."),
        ("(2+3)*4", "Це буде 20."),
        ("2^10", "Це буде 1024."),
        ("15% від 200", "Це буде 30."),
    ],
)
def test_calculator_phrases(phrase: str, reply: str, calculator: CalculatorSkill, context: DialogContext) -> None:
    result = calculator.handle(Intent(name=IntentName.CALCULATE, query=phrase), context)
    assert result.reply == reply
    assert result.success and not result.learnable


def test_calculator_division_by_zero(calculator: CalculatorSkill, context: DialogContext) -> None:
    result = calculator.handle(Intent(name=IntentName.CALCULATE, query="десять поділити на нуль"), context)
    assert result.reply == "На нуль ділити не можна, сер."
    assert not result.success


@pytest.mark.parametrize(
    "phrase",
    ["скільки коштує квиток", "", "два плюс", "скільки буде 2 5", "корінь з мінус чотири", "п'ять до десяти"],
)
def test_calculator_rejects_untranslatable(phrase: str, calculator: CalculatorSkill, context: DialogContext) -> None:
    result = calculator.handle(Intent(name=IntentName.CALCULATE, query=phrase), context)
    assert result.reply == "Не зміг порахувати, сер."
    assert not result.success and not result.learnable


@pytest.mark.parametrize(
    ("text", "expression"),
    [
        ("скільки буде двадцять п'ять помножити на чотири", "25*4"),
        ("п'ятнадцять відсотків від двохсот", "(15/100*200)"),
        ("корінь з шістдесят чотири", "sqrt(64)"),
        ("два в квадраті плюс три", "2**2+3"),
        ("сто двадцять п’ять поділене на п'ять", "125/5"),
        ("двадцять відсотків", "(20/100)"),
    ],
)
def test_translator_builds_expressions(text: str, expression: str) -> None:
    assert ExpressionTranslator().translate(text) == expression


def test_translator_raises_when_nothing_computable() -> None:
    with pytest.raises(ValueError):
        ExpressionTranslator().translate("порахуй")


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('echo')",
        "abs(-1)",
        "x + 1",
        "True + 1",
        "2 ** 1000",
        "9 ** 9 ** 9",
        "1e308 * 10",
        "(-8) ** (1/3)",
        "sqrt(-4)",
        "sqrt(4, 2)",
        "[1, 2]",
        "'a' * 3",
        "2 +",
        "",
    ],
)
def test_safe_calculator_rejects_dangerous_or_invalid(expression: str) -> None:
    with pytest.raises(ValueError):
        SafeCalculator().evaluate(expression)


def test_safe_calculator_supports_whitelisted_operations() -> None:
    calculator = SafeCalculator()
    assert calculator.evaluate("7 % 3 + 7 // 2 - -1") == 5.0
    assert calculator.evaluate("sqrt(16) * 2 ** 3") == 32.0
    with pytest.raises(ZeroDivisionError):
        calculator.evaluate("1 / 0")


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (100.0, "100"),
        (12.5, "12,5"),
        (2.0000000001, "2"),
        (-3.25, "мінус 3,25"),
        (0.05, "0,05"),
        (0.000123456, "0,0001235"),
        (0.0, "0"),
        (1 / 3, "0,3333"),
        (1.5e20, "1,5 на десять у степені 20"),
    ],
)
def test_format_number(value: float, text: str) -> None:
    assert format_number(value) == text


def system_skill(probe: FakeProbe) -> SystemInfoSkill:
    return SystemInfoSkill(probe, clock=lambda: NOW)


def ask(skill: SystemInfoSkill, kind: SystemInfoKind | None, context: DialogContext) -> str:
    result = skill.handle(Intent(name=IntentName.SYSTEM_INFO, mode=kind.value if kind else None), context)
    assert result.learnable and result.success
    return result.reply


def test_system_info_battery_charging(context: DialogContext) -> None:
    probe = FakeProbe(battery_status=BatteryStatus(76.4, True, None))
    assert ask(system_skill(probe), SystemInfoKind.BATTERY, context) == "Заряд 76%, заряджається."


def test_system_info_battery_full(context: DialogContext) -> None:
    probe = FakeProbe(battery_status=BatteryStatus(100.0, True, None))
    assert ask(system_skill(probe), SystemInfoKind.BATTERY, context) == "Заряд 100%, батарея повністю заряджена."


def test_system_info_battery_low(context: DialogContext) -> None:
    probe = FakeProbe(battery_status=BatteryStatus(23.0, False, 4800))
    assert ask(system_skill(probe), SystemInfoKind.BATTERY, context) == (
        "Заряд 23%, вистачить приблизно на 1 годину 20 хвилин. Раджу підключити зарядку, сер."
    )


def test_system_info_battery_unknown_time(context: DialogContext) -> None:
    probe = FakeProbe(battery_status=BatteryStatus(64.0, False, None))
    assert ask(system_skill(probe), SystemInfoKind.BATTERY, context) == "Заряд 64%."


def test_system_info_without_battery(context: DialogContext) -> None:
    assert ask(system_skill(FakeProbe()), SystemInfoKind.BATTERY, context) == (
        "Це стаціонарний комп'ютер, батареї немає, сер."
    )


def test_system_info_cpu(context: DialogContext) -> None:
    assert ask(system_skill(FakeProbe()), SystemInfoKind.CPU, context) == "Процесор завантажений на 14%."
    busy = ask(system_skill(FakeProbe(cpu=97.0)), SystemInfoKind.CPU, context)
    assert busy.startswith("Процесор завантажений на 97%.")


def test_system_info_memory(context: DialogContext) -> None:
    assert ask(system_skill(FakeProbe()), SystemInfoKind.MEMORY, context) == "Використано 9,6 з 16 ГБ пам'яті — 60%."


def test_system_info_disk(context: DialogContext) -> None:
    assert ask(system_skill(FakeProbe()), SystemInfoKind.DISK, context) == (
        "На системному диску вільно 120 ГБ, зайнято 72%."
    )
    small = FakeProbe(disk_status=DiskStatus(95.0, 8.0))
    assert ask(system_skill(small), SystemInfoKind.DISK, context).startswith(
        "На системному диску вільно 8 ГБ, зайнято 95%."
    )


def test_system_info_uptime(context: DialogContext) -> None:
    assert ask(system_skill(FakeProbe()), SystemInfoKind.UPTIME, context) == "Комп'ютер працює 3 години 12 хвилин."


def test_system_info_long_uptime(context: DialogContext) -> None:
    probe = FakeProbe(booted_at=NOW - timedelta(days=5, hours=1, minutes=1))
    reply = ask(system_skill(probe), SystemInfoKind.UPTIME, context)
    assert reply.startswith("Комп'ютер працює 5 днів 1 годину 1 хвилину.")
    assert "перезавантажитися" in reply


def test_system_info_overview(context: DialogContext) -> None:
    probe = FakeProbe(battery_status=BatteryStatus(80.0, True, None))
    assert ask(system_skill(probe), None, context) == (
        "Процесор завантажений на 14%. Пам'ять зайнята на 60%. Заряд 80%, заряджається."
    )
    assert ask(system_skill(FakeProbe()), SystemInfoKind.ALL, context) == (
        "Процесор завантажений на 14%. Пам'ять зайнята на 60%."
    )


@pytest.mark.parametrize(
    ("seconds", "text"),
    [(30, "менше хвилини"), (60, "1 хвилину"), (3600, "1 годину"), (86400, "1 день"), (2 * 86400 + 180, "2 дні 3 хвилини")],
)
def test_format_uptime(seconds: float, text: str) -> None:
    assert format_uptime(seconds) == text


def test_psutil_probe_reads_real_system() -> None:
    probe = PsutilProbe(cpu_interval=0.0)
    memory = probe.memory()
    disk = probe.disk()
    assert memory.total_gb > 0
    assert 0 <= memory.percent <= 100
    assert disk.free_gb >= 0
    assert probe.boot_time() < datetime.now()
    assert 0 <= probe.cpu_percent() <= 100 * 1024
