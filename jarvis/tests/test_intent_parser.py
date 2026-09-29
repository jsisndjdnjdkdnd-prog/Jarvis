from __future__ import annotations

from datetime import datetime

import pytest

from jarvis.core.intent import ActionType, IntentName, ScreenshotMode
from jarvis.nlu.intent_parser import IntentParser
from jarvis.nlu.text_normalizer import TextNormalizer


def parse(parser: IntentParser, normalizer: TextNormalizer, text: str):
    return parser.parse(normalizer.normalize(text))


@pytest.mark.parametrize(
    ("text", "target"),
    [
        ("Джарвіс, відкрий дотку", "дотку"),
        ("запусти мені гугл хром будь ласка", "гугл хром"),
        ("открой телеграм", "телеграм"),
        ("open steam", "steam"),
        ("можеш відкрити програму блокнот", "блокнот"),
    ],
)
def test_open_app(parser: IntentParser, normalizer: TextNormalizer, text: str, target: str) -> None:
    intent = parse(parser, normalizer, text)
    assert intent is not None
    assert intent.name is IntentName.OPEN_APP
    assert intent.target == target


def test_close_with_pronoun_has_no_target(parser: IntentParser, normalizer: TextNormalizer) -> None:
    intent = parse(parser, normalizer, "закрий його")
    assert intent is not None
    assert intent.name is IntentName.CLOSE_APP
    assert intent.target is None


def test_close_named_program(parser: IntentParser, normalizer: TextNormalizer) -> None:
    intent = parse(parser, normalizer, "вбий хром")
    assert intent is not None
    assert intent.name is IntentName.CLOSE_APP
    assert intent.target == "хром"


@pytest.mark.parametrize(
    ("text", "seconds"),
    [
        ("таймер на п'ять хвилин", 300),
        ("постав таймер на півтори години", 5400),
        ("таймер на годину і тридцять хвилин", 5400),
        ("засічи 90 секунд", 90),
        ("поставь таймер на пол часа", 1800),
        ("таймер на двадцять п'ять хвилин", 1500),
    ],
)
def test_timer_durations(parser: IntentParser, normalizer: TextNormalizer, text: str, seconds: int) -> None:
    intent = parse(parser, normalizer, text)
    assert intent is not None
    assert intent.name is IntentName.TIMER_SET
    assert intent.duration_seconds == seconds


def test_timer_status_and_cancel(parser: IntentParser, normalizer: TextNormalizer) -> None:
    assert parse(parser, normalizer, "скільки лишилось").name is IntentName.TIMER_STATUS
    cancel_all = parse(parser, normalizer, "скасуй всі таймери")
    assert cancel_all.name is IntentName.TIMER_CANCEL
    assert cancel_all.mode == "all"


def test_reminder_tomorrow(parser: IntentParser, normalizer: TextNormalizer) -> None:
    intent = parse(parser, normalizer, "Джарвіс, нагадай завтра о 9 подзвонити мамі")
    assert intent is not None
    assert intent.name is IntentName.REMINDER_ADD
    assert intent.when == datetime(2026, 9, 30, 9, 0)
    assert intent.message == "подзвонити мамі"


def test_reminder_relative(parser: IntentParser, normalizer: TextNormalizer) -> None:
    intent = parse(parser, normalizer, "нагадай мені через двадцять хвилин вимкнути духовку")
    assert intent.when == datetime(2026, 9, 29, 14, 20)
    assert intent.message == "вимкнути духовку"


def test_reminder_list(parser: IntentParser, normalizer: TextNormalizer) -> None:
    assert parse(parser, normalizer, "які в мене нагадування").name is IntentName.REMINDER_LIST


@pytest.mark.parametrize(
    ("text", "mode"),
    [
        ("зроби скрін", ScreenshotMode.FULL),
        ("скріншот активного вікна", ScreenshotMode.WINDOW),
        ("скрін області", ScreenshotMode.REGION),
    ],
)
def test_screenshot_modes(parser: IntentParser, normalizer: TextNormalizer, text: str, mode: ScreenshotMode) -> None:
    intent = parse(parser, normalizer, text)
    assert intent.name is IntentName.SCREENSHOT
    assert intent.mode == mode.value


@pytest.mark.parametrize(
    ("text", "name"),
    [
        ("котра година", IntentName.TIME_NOW),
        ("яке сьогодні число", IntentName.DATE_NOW),
        ("заблокуй комп'ютер", IntentName.LOCK_PC),
        ("вимкни комп'ютер", IntentName.SHUTDOWN_PC),
        ("перезавантаж комп'ютер", IntentName.RESTART_PC),
        ("вимкни звук", IntentName.MUTE),
        ("пауза", IntentName.MUSIC_PAUSE),
        ("наступний трек", IntentName.MUSIC_NEXT),
        ("що зараз грає", IntentName.MUSIC_NOW_PLAYING),
        ("вимкни музику", IntentName.MUSIC_STOP),
        ("запам'ятай, мені це подобається", IntentName.MUSIC_LIKE),
        ("онови список програм", IntentName.RESCAN_PROGRAMS),
        ("так", IntentName.CONFIRM),
        ("ні", IntentName.DENY),
        ("не те", IntentName.CORRECTION),
        ("привіт", IntentName.GREETING),
        ("дякую", IntentName.THANKS),
    ],
)
def test_simple_commands(parser: IntentParser, normalizer: TextNormalizer, text: str, name: IntentName) -> None:
    intent = parse(parser, normalizer, text)
    assert intent is not None
    assert intent.name is name


def test_volume_amounts(parser: IntentParser, normalizer: TextNormalizer) -> None:
    louder = parse(parser, normalizer, "гучніше на двадцять")
    assert louder.name is IntentName.VOLUME_UP
    assert louder.amount == 20
    exact = parse(parser, normalizer, "гучність 50")
    assert exact.name is IntentName.VOLUME_SET
    assert exact.amount == 50
    music = parse(parser, normalizer, "зроби музику тихіше")
    assert music.name is IntentName.MUSIC_VOLUME_DOWN


def test_play_specific_track(parser: IntentParser, normalizer: TextNormalizer) -> None:
    intent = parse(parser, normalizer, "постав пісню Believer від Imagine Dragons")
    assert intent.name is IntentName.PLAY_MUSIC
    assert intent.query == "believer imagine dragons"


@pytest.mark.parametrize("text", ["увімкни трек на свій вибір", "увімкни щось під настрій", "увімкни музику"])
def test_play_recommended(parser: IntentParser, normalizer: TextNormalizer, text: str) -> None:
    assert parse(parser, normalizer, text).name is IntentName.PLAY_RECOMMENDED


def test_toggle_on_known_program_opens_it(parser: IntentParser, normalizer: TextNormalizer) -> None:
    intent = parse(parser, normalizer, "увімкни хром")
    assert intent.name is IntentName.OPEN_APP
    assert intent.target == "хром"


def test_learn_binding_with_macro(parser: IntentParser, normalizer: TextNormalizer) -> None:
    intent = parse(
        parser,
        normalizer,
        'Джарвіс, запам\'ятай: коли я кажу "бойовий режим" — відкрий Discord і Dota',
    )
    assert intent.name is IntentName.LEARN_BINDING
    assert intent.phrase == "бойовий режим"
    assert [action.type for action in intent.actions] == [ActionType.OPEN_APP, ActionType.OPEN_APP]
    assert [action.target for action in intent.actions] == ["discord", "dota"]


def test_learn_binding_without_punctuation(parser: IntentParser, normalizer: TextNormalizer) -> None:
    intent = parse(parser, normalizer, "запам'ятай коли я скажу робочий день запусти телеграм та закрий стім")
    assert intent.phrase == "робочий день"
    assert [(action.type, action.target) for action in intent.actions] == [
        (ActionType.OPEN_APP, "телеграм"),
        (ActionType.CLOSE_PROCESS, "стім"),
    ]


def test_unknown_phrase_returns_none(parser: IntentParser, normalizer: TextNormalizer) -> None:
    assert parse(parser, normalizer, "яка погода в києві") is None
