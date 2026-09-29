from __future__ import annotations

from datetime import datetime

import pytest

from jarvis.core.context import DialogContext, SkillResult
from jarvis.core.intent import (
    Action,
    ActionType,
    Intent,
    IntentName,
    SmallTalkTopic,
    SystemInfoKind,
    WeatherPeriod,
    WindowCommand,
    YouTubeCommand,
)
from jarvis.nlu.geo import CityNormalizer
from jarvis.nlu.intent_parser import IntentParser
from jarvis.nlu.text_normalizer import TextNormalizer
from jarvis.nlu.time_parser import NaturalTimeParser
from jarvis.skills.plan import PlanSkill

FIXED_NOW = datetime(2026, 9, 29, 14, 0)


class Probe:
    def is_known_program(self, name: str) -> bool:
        return name in {"хром", "діскорд", "вскод", "телеграм"}


@pytest.fixture
def parser() -> IntentParser:
    return IntentParser(NaturalTimeParser(clock=lambda: FIXED_NOW, use_dateparser=False), Probe())


@pytest.fixture
def normalizer() -> TextNormalizer:
    return TextNormalizer(wake_words=["джарвіс", "джарвис", "jarvis"])


def parse(parser: IntentParser, normalizer: TextNormalizer, text: str) -> Intent | None:
    return parser.parse(normalizer.normalize(text))


@pytest.mark.parametrize(
    ("text", "amount"),
    [
        ("постав звук на 29", 29),
        ("джарвіс звук на максимум", 100),
        ("гучність на мінімум", 10),
        ("зроби звук на половину", 50),
        ("постав гучність 75", 75),
    ],
)
def test_volume_set(parser: IntentParser, normalizer: TextNormalizer, text: str, amount: int) -> None:
    intent = parse(parser, normalizer, text)
    assert intent.name is IntentName.VOLUME_SET
    assert intent.amount == amount


def test_volume_get(parser: IntentParser, normalizer: TextNormalizer) -> None:
    assert parse(parser, normalizer, "яка зараз гучність").name is IntentName.VOLUME_GET


@pytest.mark.parametrize(
    ("text", "query"),
    [
        ("увімкни на ютубі imagine dragons believer", "imagine dragons believer"),
        ("постав відео про котиків", "котиків"),
        ("знайди на youtube огляд айфона", "огляд айфона"),
    ],
)
def test_youtube_play(parser: IntentParser, normalizer: TextNormalizer, text: str, query: str) -> None:
    intent = parse(parser, normalizer, text)
    assert intent.name is IntentName.YOUTUBE_PLAY
    assert intent.query == query


def test_youtube_open_without_query(parser: IntentParser, normalizer: TextNormalizer) -> None:
    intent = parse(parser, normalizer, "відкрий ютуб")
    assert intent.name is IntentName.YOUTUBE_PLAY
    assert intent.query is None


@pytest.mark.parametrize(
    ("text", "command", "amount"),
    [
        ("постав відео на паузу", YouTubeCommand.PAUSE, None),
        ("увімкни субтитри", YouTubeCommand.SUBTITLES, None),
        ("вимкни субтитри", YouTubeCommand.SUBTITLES, None),
        ("перемотай на 30 секунд вперед", YouTubeCommand.FORWARD, 30),
        ("перемотай відео назад на хвилину", YouTubeCommand.BACKWARD, 60),
        ("наступне відео", YouTubeCommand.NEXT, None),
        ("відео на весь екран", YouTubeCommand.FULLSCREEN, None),
        ("зроби відео швидше", YouTubeCommand.FASTER, None),
    ],
)
def test_youtube_control(
    parser: IntentParser, normalizer: TextNormalizer, text: str, command: YouTubeCommand, amount: int | None
) -> None:
    intent = parse(parser, normalizer, text)
    assert intent.name is IntentName.YOUTUBE_CONTROL
    assert intent.mode == command.value
    assert intent.amount == amount


@pytest.mark.parametrize(
    ("text", "command"),
    [
        ("згорни все", WindowCommand.MINIMIZE_ALL),
        ("згорни вікно", WindowCommand.MINIMIZE),
        ("розгорни вікно", WindowCommand.MAXIMIZE),
        ("закрий вікно", WindowCommand.CLOSE),
        ("закрий всі вікна", WindowCommand.CLOSE_ALL),
        ("нова вкладка", WindowCommand.NEW_TAB),
        ("закрий вкладку", WindowCommand.CLOSE_TAB),
        ("онови сторінку", WindowCommand.REFRESH),
        ("прокрути вниз", WindowCommand.SCROLL_DOWN),
        ("скопіюй", WindowCommand.COPY),
        ("встав", WindowCommand.PASTE),
    ],
)
def test_window_control(
    parser: IntentParser, normalizer: TextNormalizer, text: str, command: WindowCommand
) -> None:
    intent = parse(parser, normalizer, text)
    assert intent.name is IntentName.WINDOW_CONTROL
    assert intent.mode == command.value


def test_type_text(parser: IntentParser, normalizer: TextNormalizer) -> None:
    intent = parse(parser, normalizer, "напиши привіт як твої справи")
    assert intent.name is IntentName.TYPE_TEXT
    assert intent.message == "привіт як твої справи"


@pytest.mark.parametrize(
    ("text", "topic"),
    [
        ("як настрій", SmallTalkTopic.MOOD),
        ("хто ти", SmallTalkTopic.IDENTITY),
        ("хто тебе створив", SmallTalkTopic.CREATOR),
        ("розкажи жарт", SmallTalkTopic.JOKE),
        ("ти найкращий", SmallTalkTopic.COMPLIMENT),
        ("на добраніч", SmallTalkTopic.GOODNIGHT),
        ("я вдома", SmallTalkTopic.WELCOME_HOME),
        ("мені нудно", SmallTalkTopic.BORED),
        ("поговори зі мною", SmallTalkTopic.GENERIC),
    ],
)
def test_small_talk(
    parser: IntentParser, normalizer: TextNormalizer, text: str, topic: SmallTalkTopic
) -> None:
    intent = parse(parser, normalizer, text)
    assert intent.name is IntentName.SMALL_TALK
    assert intent.mode == topic.value


@pytest.mark.parametrize(
    ("text", "name"),
    [
        ("що ти вмієш", IntentName.CAPABILITIES),
        ("повтори", IntentName.REPEAT),
        ("замовкни", IntentName.STOP_SPEAKING),
        ("дякую все", IntentName.END_CONVERSATION),
        ("відпочинь", IntentName.END_CONVERSATION),
        ("попередній трек", IntentName.MUSIC_PREVIOUS),
        ("очисти кошик", IntentName.EMPTY_RECYCLE_BIN),
        ("переведи комп'ютер в режим сну", IntentName.SLEEP_PC),
    ],
)
def test_simple_new_intents(
    parser: IntentParser, normalizer: TextNormalizer, text: str, name: IntentName
) -> None:
    assert parse(parser, normalizer, text).name is name


def test_listen_mode(parser: IntentParser, normalizer: TextNormalizer) -> None:
    assert parse(parser, normalizer, "слухай мене постійно").mode == "always"
    assert parse(parser, normalizer, "перестань слухати постійно").mode == "wake"


@pytest.mark.parametrize(
    ("text", "city", "period"),
    [
        ("яка погода", None, WeatherPeriod.NOW),
        ("яка погода в києві", "Київ", WeatherPeriod.NOW),
        ("погода на завтра у львові", "Львів", WeatherPeriod.TOMORROW),
        ("чи буде дощ завтра", None, WeatherPeriod.TOMORROW),
    ],
)
def test_weather(
    parser: IntentParser, normalizer: TextNormalizer, text: str, city: str | None, period: WeatherPeriod
) -> None:
    intent = parse(parser, normalizer, text)
    assert intent.name is IntentName.WEATHER
    assert intent.target == city
    assert intent.mode == period.value


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("скільки заряду", SystemInfoKind.BATTERY),
        ("навантаження процесора", SystemInfoKind.CPU),
        ("скільки оперативки", SystemInfoKind.MEMORY),
        ("скільки місця на диску", SystemInfoKind.DISK),
        ("стан системи", SystemInfoKind.ALL),
    ],
)
def test_system_info(
    parser: IntentParser, normalizer: TextNormalizer, text: str, kind: SystemInfoKind
) -> None:
    intent = parse(parser, normalizer, text)
    assert intent.name is IntentName.SYSTEM_INFO
    assert intent.mode == kind.value


def test_calculate(parser: IntentParser, normalizer: TextNormalizer) -> None:
    intent = parse(parser, normalizer, "скільки буде двадцять п'ять помножити на чотири")
    assert intent.name is IntentName.CALCULATE
    assert "25" in intent.query


def test_web_search(parser: IntentParser, normalizer: TextNormalizer) -> None:
    intent = parse(parser, normalizer, "загугли курс долара")
    assert intent.name is IntentName.WEB_SEARCH
    assert intent.query == "курс долара"


def test_open_settings(parser: IntentParser, normalizer: TextNormalizer) -> None:
    intent = parse(parser, normalizer, "відкрий налаштування блютуз")
    assert intent.name is IntentName.OPEN_SETTINGS
    assert intent.target == "bluetooth"


def test_alarm_sets_reminder(parser: IntentParser, normalizer: TextNormalizer) -> None:
    intent = parse(parser, normalizer, "розбуди мене о 7 ранку")
    assert intent.name is IntentName.REMINDER_ADD
    assert intent.when == datetime(2026, 9, 30, 7, 0)


@pytest.mark.parametrize(
    ("text", "steps"),
    [
        ("закрий всі вікна і відкрий хром", [IntentName.WINDOW_CONTROL, IntentName.OPEN_APP]),
        ("зроби скріншот і відкрий папку завантаження", [IntentName.SCREENSHOT, IntentName.OPEN_FOLDER]),
        ("закрий діскорд і доту", [IntentName.CLOSE_APP, IntentName.CLOSE_APP]),
        ("закрий хром потім відкрий ютуб", [IntentName.CLOSE_APP, IntentName.YOUTUBE_PLAY]),
    ],
)
def test_compound_plan(
    parser: IntentParser, normalizer: TextNormalizer, text: str, steps: list[IntentName]
) -> None:
    intent = parse(parser, normalizer, text)
    assert intent.name is IntentName.RUN_PLAN
    resolved = [
        action.intent.name if action.intent is not None else _ACTION_TO_INTENT[action.type]
        for action in intent.actions
    ]
    assert resolved == steps


def test_compound_ignores_non_chainable(parser: IntentParser, normalizer: TextNormalizer) -> None:
    assert parse(parser, normalizer, "таймер на годину і 30 хвилин").name is IntentName.TIMER_SET


_ACTION_TO_INTENT = {
    ActionType.OPEN_APP: IntentName.OPEN_APP,
    ActionType.CLOSE_PROCESS: IntentName.CLOSE_APP,
    ActionType.OPEN_FOLDER: IntentName.OPEN_FOLDER,
    ActionType.LAUNCH: IntentName.OPEN_URL,
    ActionType.PLAY_TRACK: IntentName.PLAY_MUSIC,
}


class FakeExecutor:
    def __init__(self, results: dict[str, SkillResult]) -> None:
        self._results = results
        self.executed: list[str] = []

    def execute(self, action: Action, context: DialogContext, depth: int = 0) -> SkillResult:
        key = action.describe()
        self.executed.append(key)
        return self._results.get(key, SkillResult("Готово"))


def plan_intent(*intents: Intent) -> Intent:
    return Intent(
        name=IntentName.RUN_PLAN,
        actions=tuple(Action(type=ActionType.INTENT, intent=item) for item in intents),
    )


def test_plan_runs_all_steps() -> None:
    executor = FakeExecutor({})
    skill = PlanSkill(executor)
    intent = plan_intent(
        Intent(name=IntentName.WINDOW_CONTROL, mode="close_all"),
        Intent(name=IntentName.OPEN_APP, target="хром"),
    )
    result = skill.handle(intent, DialogContext())
    assert len(executor.executed) == 2
    assert result.success


def test_plan_short_circuits_on_first_confirmation() -> None:
    from jarvis.core.context import PendingConfirmation

    confirmation = PendingConfirmation("вимкнути ПК", lambda: SkillResult("ok"))
    executor = FakeExecutor(
        {"intent:shutdown_pc": SkillResult("Впевнені?", confirmation=confirmation)}
    )
    skill = PlanSkill(executor)
    intent = plan_intent(
        Intent(name=IntentName.SHUTDOWN_PC),
        Intent(name=IntentName.OPEN_APP, target="хром"),
    )
    result = skill.handle(intent, DialogContext())
    assert result.confirmation is confirmation
    assert executor.executed == ["intent:shutdown_pc"]


def test_city_normalizer() -> None:
    normalizer = CityNormalizer()
    assert normalizer.normalize("києві") == "Київ"
    assert normalizer.normalize("львові") == "Львів"
    assert normalizer.normalize("одесі") == "Одеса"
