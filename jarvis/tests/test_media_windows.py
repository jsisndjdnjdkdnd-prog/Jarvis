from __future__ import annotations

from collections.abc import Sequence

import pytest

from jarvis.core.config import MusicSection
from jarvis.core.context import DialogContext
from jarvis.core.errors import (
    ActionExecutionError,
    MusicError,
    PlatformNotSupportedError,
    SkillError,
    TrackNotFoundError,
)
from jarvis.core.event_bus import EventBus
from jarvis.core.intent import Intent, IntentName, WindowCommand, YouTubeCommand
from jarvis.core.models import PlayedTrack, Track
from jarvis.skills.base import SkillDispatcher, SkillRegistry
from jarvis.skills.input_control import LAYOUT_INDEPENDENT_KEYS, MediaKey, WindowsInputController, keyboard_keys
from jarvis.skills.media_soundcloud.player import FinishedCallback
from jarvis.skills.media_soundcloud.recommender import TrackSuggestion
from jarvis.skills.media_soundcloud.search import TrackRanker
from jarvis.skills.media_soundcloud.skill import MusicService, MusicSkill
from jarvis.skills.platform import is_windows
from jarvis.skills.window_control import SHORTCUTS as WINDOW_SHORTCUTS
from jarvis.skills.window_control import WindowControlSkill
from jarvis.skills.window_manager import Win32WindowManager, title_matches
from jarvis.skills.youtube_control import SHORTCUTS as VIDEO_SHORTCUTS
from jarvis.skills.youtube_control import YouTubeControlSkill, plan_seek
from jarvis.storage.repositories import Repositories

WINDOWS_KEY_NAMES: frozenset[str] = frozenset(
    {"ctrl", "alt", "shift", "windows", "tab", "left", "right", "page up", "page down", "f5", "f11"}
    | set("abcdefghijklmnopqrstuvwxyz")
)

SPECIFIED_WINDOW_COMMANDS: frozenset[str] = frozenset(
    {
        "minimize_all", "minimize", "maximize", "restore", "close", "switch", "new_tab", "close_tab",
        "reopen_tab", "next_tab", "refresh", "back", "forward", "zoom_in", "zoom_out", "scroll_down",
        "scroll_up", "fullscreen", "copy", "paste", "undo", "select_all", "save",
    }
)

TRACK_A = Track(title="Alpha", artist="Artist", url="https://soundcloud.com/a")
TRACK_B = Track(title="Beta", artist="Artist", url="https://soundcloud.com/b")
TRACK_C = Track(title="Gamma", artist="Artist", url="https://soundcloud.com/c")


class FakeInput:
    def __init__(self) -> None:
        self.media: list[MediaKey] = []
        self.sent: list[str] = []
        self.written: list[str] = []

    def press_media(self, key: MediaKey) -> None:
        self.media.append(key)

    def send(self, combination: str) -> None:
        self.sent.append(combination)

    def write(self, text: str) -> None:
        self.written.append(text)


class FakeWindows:
    def __init__(self, handle: int | None = 42, focus_result: bool = True) -> None:
        self.handle = handle
        self.focus_result = focus_result
        self.searches: list[tuple[str, ...]] = []
        self.calls: list[str] = []

    def find(self, title_keywords: Sequence[str]) -> int | None:
        self.searches.append(tuple(title_keywords))
        return self.handle

    def focus(self, handle: int) -> bool:
        self.calls.append(f"focus:{handle}")
        return self.focus_result

    def foreground_title(self) -> str:
        return "Документ"

    def minimize_foreground(self) -> None:
        self.calls.append("minimize")

    def maximize_foreground(self) -> None:
        self.calls.append("maximize")

    def restore_foreground(self) -> None:
        self.calls.append("restore")

    def close_foreground(self) -> None:
        self.calls.append("close")


class FakePlayer:
    def __init__(self, supports_control: bool = True) -> None:
        self._supports_control = supports_control
        self.played: list[Track] = []
        self.calls: list[str] = []
        self.on_finished: FinishedCallback | None = None

    @property
    def supports_control(self) -> bool:
        return self._supports_control

    def play(self, track: Track) -> None:
        self.played.append(track)

    def pause(self) -> None:
        self.calls.append("pause")

    def resume(self) -> None:
        self.calls.append("resume")

    def stop(self) -> None:
        self.calls.append("stop")

    def change_volume(self, delta: int) -> int:
        return 70 + delta

    def set_on_finished(self, callback: FinishedCallback) -> None:
        self.on_finished = callback

    def finish(self) -> None:
        if self.on_finished is not None:
            self.on_finished()


class FakeSearch:
    def __init__(self, results: dict[str, list[Track]]) -> None:
        self._results = results

    def search(self, query: str, limit: int) -> list[Track]:
        return list(self._results.get(query, []))


class KeepOrderRanker(TrackRanker):
    def rank(self, query: str, tracks: Sequence[Track]) -> list[Track]:
        return list(tracks)

    def best(self, query: str, tracks: Sequence[Track]) -> Track:
        if not tracks:
            raise TrackNotFoundError(f"Не знайшов «{query}» на SoundCloud, сер.")
        return tracks[0]


class FakeRecommender:
    def suggest(self, hint: str | None, recent: Sequence[PlayedTrack]) -> TrackSuggestion:
        return TrackSuggestion(artist="Radio", title="Mix")


class MusicHarness:
    def __init__(self, repositories: Repositories, supports_control: bool = True, radio: list[Track] | None = None) -> None:
        self.player = FakePlayer(supports_control)
        self.keys = FakeInput()
        search = FakeSearch({"alpha": [TRACK_A, TRACK_B, TRACK_C], "Radio Mix": radio or []})
        self.service = MusicService(
            search,
            KeepOrderRanker(),
            self.player,
            FakeRecommender(),
            repositories.preferences,
            repositories.listening,
            EventBus(),
            MusicSection(),
        )
        self.skill = MusicSkill(self.service, MusicSection(), self.keys)
        registry = SkillRegistry()
        registry.register(self.skill)
        self.dispatcher = SkillDispatcher(registry)
        self.context = DialogContext()

    def say(self, name: IntentName, **slots: object) -> tuple[str, bool]:
        result = self.dispatcher.dispatch(Intent(name=name, **slots), self.context)
        return result.reply, result.success


def window_intent(mode: str | None, amount: int | None = None) -> Intent:
    return Intent(name=IntentName.WINDOW_CONTROL, mode=mode, amount=amount)


def video_intent(mode: str | None, amount: int | None = None, duration_seconds: int | None = None) -> Intent:
    return Intent(name=IntentName.YOUTUBE_CONTROL, mode=mode, amount=amount, duration_seconds=duration_seconds)


@pytest.fixture
def keys() -> FakeInput:
    return FakeInput()


@pytest.fixture
def windows() -> FakeWindows:
    return FakeWindows()


@pytest.fixture
def window_skill(keys: FakeInput, windows: FakeWindows) -> WindowControlSkill:
    return WindowControlSkill(keys, windows)


@pytest.fixture
def settles() -> list[float]:
    return []


@pytest.fixture
def video_skill(keys: FakeInput, windows: FakeWindows, settles: list[float]) -> YouTubeControlSkill:
    return YouTubeControlSkill(keys, windows, settle=settles.append)


def test_window_skill_declares_intents(window_skill: WindowControlSkill) -> None:
    assert window_skill.name == "window_control"
    assert window_skill.intents == frozenset({IntentName.WINDOW_CONTROL, IntentName.TYPE_TEXT})


@pytest.mark.parametrize(
    ("command", "combination", "reply"),
    [
        (WindowCommand.MINIMIZE_ALL, "windows+d", "Згорнув усі вікна."),
        (WindowCommand.NEW_TAB, "ctrl+t", "Нова вкладка."),
        (WindowCommand.CLOSE_TAB, "ctrl+w", "Закрив вкладку."),
        (WindowCommand.REOPEN_TAB, "ctrl+shift+t", "Повернув закриту вкладку."),
        (WindowCommand.NEXT_TAB, "ctrl+tab", "Наступна вкладка."),
        (WindowCommand.REFRESH, "f5", "Оновив сторінку."),
        (WindowCommand.BACK, "alt+left", "Повернувся назад."),
        (WindowCommand.FORWARD, "alt+right", "Перейшов уперед."),
        (WindowCommand.ZOOM_IN, "ctrl+plus", "Збільшив масштаб."),
        (WindowCommand.ZOOM_OUT, "ctrl+minus", "Зменшив масштаб."),
        (WindowCommand.SCROLL_DOWN, "page down", "Прокрутив униз."),
        (WindowCommand.SCROLL_UP, "page up", "Прокрутив угору."),
        (WindowCommand.FULLSCREEN, "f11", "Перемкнув повноекранний режим."),
        (WindowCommand.COPY, "ctrl+c", "Скопіював."),
        (WindowCommand.PASTE, "ctrl+v", "Вставив."),
        (WindowCommand.UNDO, "ctrl+z", "Скасував останню дію."),
        (WindowCommand.SELECT_ALL, "ctrl+a", "Виділив усе."),
        (WindowCommand.SAVE, "ctrl+s", "Зберіг."),
        (WindowCommand.SWITCH, "alt+tab", "Перемкнув вікно."),
    ],
)
def test_window_shortcuts(
    window_skill: WindowControlSkill,
    keys: FakeInput,
    windows: FakeWindows,
    command: WindowCommand,
    combination: str,
    reply: str,
) -> None:
    result = window_skill.handle(window_intent(command.value), DialogContext())
    assert keys.sent == [combination]
    assert result.reply == reply
    assert result.success
    assert result.learnable
    assert windows.calls == []


@pytest.mark.parametrize(
    ("command", "call", "reply", "learnable"),
    [
        (WindowCommand.MINIMIZE, "minimize", "Згорнув вікно.", True),
        (WindowCommand.MAXIMIZE, "maximize", "Розгорнув вікно.", True),
        (WindowCommand.RESTORE, "restore", "Відновив вікно.", True),
        (WindowCommand.CLOSE, "close", "Закрив вікно.", False),
    ],
)
def test_window_operations_use_window_manager(
    window_skill: WindowControlSkill,
    keys: FakeInput,
    windows: FakeWindows,
    command: WindowCommand,
    call: str,
    reply: str,
    learnable: bool,
) -> None:
    result = window_skill.handle(window_intent(command.value), DialogContext())
    assert windows.calls == [call]
    assert keys.sent == []
    assert result.reply == reply
    assert result.learnable is learnable


def test_every_specified_window_command_is_handled(window_skill: WindowControlSkill) -> None:
    for value in SPECIFIED_WINDOW_COMMANDS:
        assert window_skill.handle(window_intent(value), DialogContext()).success, value


def test_unmapped_window_commands_fail_politely(window_skill: WindowControlSkill, keys: FakeInput, windows: FakeWindows) -> None:
    for command in WindowCommand:
        if command.value in SPECIFIED_WINDOW_COMMANDS:
            continue
        result = window_skill.handle(window_intent(command.value), DialogContext())
        assert not result.success
        assert result.reply.endswith(".")
    assert keys.sent == []
    assert windows.calls == []


def test_close_all_is_refused_safely(window_skill: WindowControlSkill, windows: FakeWindows) -> None:
    if "close_all" not in {command.value for command in WindowCommand}:
        pytest.skip("WindowCommand.CLOSE_ALL відсутня")
    result = window_skill.handle(window_intent("close_all"), DialogContext())
    assert not result.success
    assert "не ризикну" in result.reply
    assert windows.calls == []


@pytest.mark.parametrize(
    ("command", "amount", "expected"),
    [
        (WindowCommand.SCROLL_DOWN, 3, ["page down"] * 3),
        (WindowCommand.SCROLL_UP, 25, ["page up"] * 10),
        (WindowCommand.ZOOM_IN, 2, ["ctrl+plus"] * 2),
        (WindowCommand.ZOOM_OUT, 0, ["ctrl+minus"]),
        (WindowCommand.NEXT_TAB, 2, ["ctrl+tab"] * 2),
        (WindowCommand.REFRESH, 5, ["f5"]),
        (WindowCommand.SAVE, 3, ["ctrl+s"]),
    ],
)
def test_amount_repeats_only_repeatable_actions(
    window_skill: WindowControlSkill, keys: FakeInput, command: WindowCommand, amount: int, expected: list[str]
) -> None:
    window_skill.handle(window_intent(command.value, amount), DialogContext())
    assert keys.sent == expected


def test_switch_holds_alt_for_several_windows(window_skill: WindowControlSkill, keys: FakeInput) -> None:
    window_skill.handle(window_intent(WindowCommand.SWITCH.value, 3), DialogContext())
    window_skill.handle(window_intent(WindowCommand.SWITCH.value, 99), DialogContext())
    assert keys.sent == ["alt+tab+tab+tab", "alt+" + "+".join(["tab"] * 10)]


def test_window_mode_is_normalized(window_skill: WindowControlSkill, windows: FakeWindows) -> None:
    result = window_skill.handle(window_intent("  MINIMIZE "), DialogContext())
    assert result.success
    assert windows.calls == ["minimize"]


@pytest.mark.parametrize("mode", [None, "", "dance", "minimise"])
def test_unknown_window_command_is_polite_failure(
    window_skill: WindowControlSkill, keys: FakeInput, windows: FakeWindows, mode: str | None
) -> None:
    result = window_skill.handle(window_intent(mode), DialogContext())
    assert not result.success
    assert not result.learnable
    assert result.reply == "Не зрозумів, що зробити з вікном, сер."
    assert keys.sent == []
    assert windows.calls == []


def test_type_text_writes_message(window_skill: WindowControlSkill, keys: FakeInput) -> None:
    result = window_skill.handle(Intent(name=IntentName.TYPE_TEXT, message=" Привіт, світе! "), DialogContext())
    assert keys.written == ["Привіт, світе!"]
    assert result.reply == "Надрукував."
    assert result.success


@pytest.mark.parametrize("message", [None, "", "   "])
def test_type_text_without_message_asks_what_to_type(
    window_skill: WindowControlSkill, keys: FakeInput, message: str | None
) -> None:
    result = window_skill.handle(Intent(name=IntentName.TYPE_TEXT, message=message), DialogContext())
    assert keys.written == []
    assert not result.success
    assert result.reply == "Що саме надрукувати, сер?"


def test_video_skill_declares_intents(video_skill: YouTubeControlSkill) -> None:
    assert video_skill.name == "youtube_control"
    assert video_skill.intents == frozenset({IntentName.YOUTUBE_CONTROL})


@pytest.mark.parametrize(
    ("command", "combination", "reply"),
    [
        (YouTubeCommand.TOGGLE, "k", "Перемкнув відтворення."),
        (YouTubeCommand.PAUSE, "k", "Пауза."),
        (YouTubeCommand.PLAY, "k", "Продовжую."),
        (YouTubeCommand.SUBTITLES, "c", "Субтитри перемкнув."),
        (YouTubeCommand.FULLSCREEN, "f", "Повноекранний режим перемкнув."),
        (YouTubeCommand.MUTE, "m", "Звук відео перемкнув."),
        (YouTubeCommand.THEATER, "t", "Режим кінотеатру перемкнув."),
        (YouTubeCommand.NEXT, "shift+n", "Наступне відео."),
        (YouTubeCommand.PREVIOUS, "shift+p", "Попереднє відео."),
        (YouTubeCommand.FASTER, "shift+period", "Пришвидшив відтворення."),
        (YouTubeCommand.SLOWER, "shift+comma", "Сповільнив відтворення."),
    ],
)
def test_video_shortcuts_focus_window_first(
    video_skill: YouTubeControlSkill,
    keys: FakeInput,
    windows: FakeWindows,
    settles: list[float],
    command: YouTubeCommand,
    combination: str,
    reply: str,
) -> None:
    result = video_skill.handle(video_intent(command.value), DialogContext())
    assert windows.searches == [("YouTube",)]
    assert windows.calls == ["focus:42"]
    assert settles == [0.25]
    assert keys.sent == [combination]
    assert result.reply == reply
    assert result.success


@pytest.mark.parametrize(
    ("command", "amount", "expected", "reply"),
    [
        (YouTubeCommand.FORWARD, 25, ["l", "l", "right"], "Перемотав на 25 секунд вперед."),
        (YouTubeCommand.FORWARD, 30, ["l", "l", "l"], "Перемотав на 30 секунд вперед."),
        (YouTubeCommand.FORWARD, 5, ["right"], "Перемотав на 5 секунд вперед."),
        (YouTubeCommand.FORWARD, None, ["l"], "Перемотав на 10 секунд вперед."),
        (YouTubeCommand.FORWARD, 12, ["l"], "Перемотав на 10 секунд вперед."),
        (YouTubeCommand.BACKWARD, 3, ["left"], "Перемотав на 5 секунд назад."),
        (YouTubeCommand.BACKWARD, 15, ["j", "left"], "Перемотав на 15 секунд назад."),
        (YouTubeCommand.BACKWARD, None, ["j"], "Перемотав на 10 секунд назад."),
    ],
)
def test_video_seek(
    video_skill: YouTubeControlSkill,
    keys: FakeInput,
    command: YouTubeCommand,
    amount: int | None,
    expected: list[str],
    reply: str,
) -> None:
    result = video_skill.handle(video_intent(command.value, amount), DialogContext())
    assert keys.sent == expected
    assert result.reply == reply


def test_video_seek_prefers_duration(video_skill: YouTubeControlSkill, keys: FakeInput) -> None:
    result = video_skill.handle(video_intent(YouTubeCommand.FORWARD.value, 2, 90), DialogContext())
    assert keys.sent == ["l"] * 9
    assert result.reply == "Перемотав на 1 хвилину 30 секунд вперед."


def test_video_seek_is_bounded(video_skill: YouTubeControlSkill, keys: FakeInput) -> None:
    video_skill.handle(video_intent(YouTubeCommand.FORWARD.value, 100000), DialogContext())
    assert keys.sent == ["l"] * 60


@pytest.mark.parametrize(
    ("seconds", "long_presses", "short_presses", "total"),
    [(25, 2, 1, 25), (30, 3, 0, 30), (5, 0, 1, 5), (1, 0, 1, 5), (0, 0, 1, 5), (-7, 0, 1, 5), (19, 1, 1, 15)],
)
def test_plan_seek(seconds: int, long_presses: int, short_presses: int, total: int) -> None:
    plan = plan_seek(seconds)
    assert (plan.long_presses, plan.short_presses, plan.seconds) == (long_presses, short_presses, total)


def test_video_missing_window_raises_polite_error(keys: FakeInput, settles: list[float]) -> None:
    skill = YouTubeControlSkill(keys, FakeWindows(handle=None), settle=settles.append)
    with pytest.raises(SkillError, match="Не бачу відкритого YouTube, сер."):
        skill.handle(video_intent(YouTubeCommand.PAUSE.value), DialogContext())
    assert keys.sent == []
    assert settles == []


def test_video_missing_window_is_spoken_through_dispatcher(keys: FakeInput) -> None:
    registry = SkillRegistry()
    registry.register(YouTubeControlSkill(keys, FakeWindows(handle=None), settle=lambda _: None))
    result = SkillDispatcher(registry).dispatch(video_intent(YouTubeCommand.PAUSE.value), DialogContext())
    assert result.reply == "Не бачу відкритого YouTube, сер."
    assert not result.success


def test_video_keeps_trying_when_focus_fails(keys: FakeInput, settles: list[float]) -> None:
    windows = FakeWindows(handle=7, focus_result=False)
    skill = YouTubeControlSkill(keys, windows, settle=settles.append)
    result = skill.handle(video_intent(YouTubeCommand.MUTE.value), DialogContext())
    assert windows.calls == ["focus:7"]
    assert keys.sent == ["m"]
    assert result.success


def test_video_uses_custom_title_keywords(keys: FakeInput, windows: FakeWindows) -> None:
    skill = YouTubeControlSkill(keys, windows, title_keywords=("YouTube", "Ютуб"), settle=lambda _: None)
    skill.handle(video_intent(YouTubeCommand.TOGGLE.value), DialogContext())
    assert windows.searches == [("YouTube", "Ютуб")]


@pytest.mark.parametrize("mode", [None, "", "explode"])
def test_video_unknown_command(
    video_skill: YouTubeControlSkill, keys: FakeInput, windows: FakeWindows, mode: str | None
) -> None:
    result = video_skill.handle(video_intent(mode), DialogContext())
    assert not result.success
    assert result.reply == "Не зрозумів, що зробити з відео, сер."
    assert windows.searches == []
    assert keys.sent == []


def test_every_video_command_is_handled(video_skill: YouTubeControlSkill) -> None:
    for command in YouTubeCommand:
        assert video_skill.handle(video_intent(command.value), DialogContext()).success, command


def test_keyboard_keys_use_virtual_keys_for_punctuation() -> None:
    assert keyboard_keys("ctrl+plus") == ["ctrl", -0xBB]
    assert keyboard_keys("ctrl+minus") == ["ctrl", -0xBD]
    assert keyboard_keys("shift+period") == ["shift", -0xBE]
    assert keyboard_keys("shift+comma") == ["shift", -0xBC]
    assert keyboard_keys("Windows + D") == ["windows", "d"]
    assert keyboard_keys("page down") == ["page down"]


@pytest.mark.parametrize("combination", ["", "ctrl+", "+", "alt++tab"])
def test_keyboard_keys_reject_broken_combinations(combination: str) -> None:
    with pytest.raises(ActionExecutionError):
        keyboard_keys(combination)


def test_all_combinations_use_canonical_key_names() -> None:
    combinations = [shortcut.combination for shortcut in WINDOW_SHORTCUTS.values()]
    combinations += [shortcut.combination for shortcut in VIDEO_SHORTCUTS.values()]
    combinations += ["alt+tab", "l", "j", "right", "left"]
    for combination in combinations:
        for key in keyboard_keys(combination):
            assert isinstance(key, int) or key in WINDOWS_KEY_NAMES, (combination, key)


def test_canonical_names_match_keyboard_package() -> None:
    canonical = pytest.importorskip("keyboard._canonical_names")
    for name in WINDOWS_KEY_NAMES:
        assert canonical.normalize_name(name) == name
    for name in LAYOUT_INDEPENDENT_KEYS:
        assert canonical.normalize_name(name) != name


@pytest.mark.skipif(is_windows(), reason="перевірка поведінки поза Windows")
def test_windows_input_controller_requires_windows() -> None:
    controller = WindowsInputController()
    with pytest.raises(PlatformNotSupportedError):
        controller.press_media(MediaKey.PLAY_PAUSE)
    with pytest.raises(PlatformNotSupportedError):
        controller.send("ctrl+t")
    with pytest.raises(PlatformNotSupportedError):
        controller.write("текст")


@pytest.mark.skipif(is_windows(), reason="перевірка поведінки поза Windows")
def test_window_manager_requires_windows() -> None:
    manager = Win32WindowManager()
    with pytest.raises(PlatformNotSupportedError):
        manager.find(["YouTube"])
    with pytest.raises(PlatformNotSupportedError):
        manager.focus(1)
    with pytest.raises(PlatformNotSupportedError):
        manager.close_foreground()


def test_title_matches_is_case_insensitive() -> None:
    assert title_matches("Lo-fi beats - YouTube - Google Chrome", ["youtube"])
    assert title_matches("Відео — ЮТУБ", ["ютуб"])
    assert not title_matches("Документ - Word", ["YouTube"])
    assert not title_matches("Будь-що", ["", "  "])


def test_music_skill_declares_previous(repositories: Repositories) -> None:
    assert IntentName.MUSIC_PREVIOUS in MusicHarness(repositories).skill.intents


@pytest.mark.parametrize(
    ("intent_name", "media_key", "reply"),
    [
        (IntentName.MUSIC_PAUSE, MediaKey.PLAY_PAUSE, "Пауза."),
        (IntentName.MUSIC_RESUME, MediaKey.PLAY_PAUSE, "Продовжую."),
        (IntentName.MUSIC_NEXT, MediaKey.NEXT, "Наступний."),
        (IntentName.MUSIC_PREVIOUS, MediaKey.PREVIOUS, "Попередній."),
        (IntentName.MUSIC_STOP, MediaKey.STOP, "Зупинив."),
    ],
)
def test_idle_player_routes_to_media_keys(
    repositories: Repositories, intent_name: IntentName, media_key: MediaKey, reply: str
) -> None:
    harness = MusicHarness(repositories)
    assert harness.say(intent_name) == (reply, True)
    assert harness.keys.media == [media_key]
    assert harness.player.calls == []
    assert harness.player.played == []


@pytest.mark.parametrize(
    ("intent_name", "media_key"),
    [
        (IntentName.MUSIC_PAUSE, MediaKey.PLAY_PAUSE),
        (IntentName.MUSIC_NEXT, MediaKey.NEXT),
        (IntentName.MUSIC_STOP, MediaKey.STOP),
    ],
)
def test_browser_player_routes_to_media_keys(
    repositories: Repositories, intent_name: IntentName, media_key: MediaKey
) -> None:
    harness = MusicHarness(repositories, supports_control=False)
    harness.say(IntentName.PLAY_MUSIC, query="alpha")
    assert not harness.service.is_active
    harness.say(intent_name)
    assert harness.keys.media == [media_key]
    assert harness.player.calls == []


def test_active_player_is_controlled_directly(repositories: Repositories) -> None:
    harness = MusicHarness(repositories)
    assert harness.say(IntentName.PLAY_MUSIC, query="alpha") == ("Вмикаю Artist — Alpha.", True)
    assert harness.service.is_active
    assert harness.say(IntentName.MUSIC_PAUSE) == ("Пауза.", True)
    assert harness.say(IntentName.MUSIC_RESUME) == ("Продовжую.", True)
    assert harness.say(IntentName.MUSIC_NEXT) == ("Далі: Artist — Beta.", True)
    assert harness.say(IntentName.MUSIC_STOP) == ("Музику вимкнено.", True)
    assert harness.player.calls == ["pause", "resume", "stop"]
    assert harness.keys.media == []
    assert not harness.service.is_active


def test_previous_replays_earlier_track_and_requeues_current(repositories: Repositories) -> None:
    harness = MusicHarness(repositories)
    harness.say(IntentName.PLAY_MUSIC, query="alpha")
    harness.say(IntentName.MUSIC_NEXT)
    assert harness.say(IntentName.MUSIC_PREVIOUS) == ("Повертаю: Artist — Alpha.", True)
    assert harness.service.current == TRACK_A
    assert harness.context.last_track == TRACK_A
    assert harness.say(IntentName.MUSIC_NEXT) == ("Далі: Artist — Beta.", True)
    assert harness.say(IntentName.MUSIC_NEXT) == ("Далі: Artist — Gamma.", True)
    assert harness.player.played == [TRACK_A, TRACK_B, TRACK_A, TRACK_B, TRACK_C]
    assert harness.keys.media == []


def test_previous_walks_back_through_session(repositories: Repositories) -> None:
    harness = MusicHarness(repositories)
    harness.say(IntentName.PLAY_MUSIC, query="alpha")
    harness.say(IntentName.MUSIC_NEXT)
    harness.say(IntentName.MUSIC_NEXT)
    harness.say(IntentName.MUSIC_PREVIOUS)
    harness.say(IntentName.MUSIC_PREVIOUS)
    assert harness.service.current == TRACK_A
    assert harness.say(IntentName.MUSIC_PREVIOUS) == ("Попереднього треку немає, сер.", False)
    assert harness.service.current == TRACK_A


def test_previous_without_history_is_polite(repositories: Repositories) -> None:
    harness = MusicHarness(repositories)
    harness.say(IntentName.PLAY_MUSIC, query="alpha")
    assert harness.say(IntentName.MUSIC_PREVIOUS) == ("Попереднього треку немає, сер.", False)
    assert harness.keys.media == []


def test_service_previous_after_stop_replays_last_track(repositories: Repositories) -> None:
    harness = MusicHarness(repositories)
    harness.service.play_query("alpha")
    harness.service.next()
    harness.service.stop()
    assert harness.service.previous() == TRACK_B
    assert harness.service.current == TRACK_B


def test_service_previous_on_fresh_session_raises(repositories: Repositories) -> None:
    harness = MusicHarness(repositories)
    with pytest.raises(MusicError, match="Попереднього треку немає, сер."):
        harness.service.previous()


def test_now_playing_when_idle(repositories: Repositories) -> None:
    harness = MusicHarness(repositories)
    assert harness.say(IntentName.MUSIC_NOW_PLAYING) == ("У моєму плеєрі зараз нічого не грає, сер.", True)
    harness.say(IntentName.PLAY_MUSIC, query="alpha")
    assert harness.say(IntentName.MUSIC_NOW_PLAYING) == ("Зараз грає Artist — Alpha.", True)


def test_finished_track_without_continuation_makes_player_idle(repositories: Repositories) -> None:
    harness = MusicHarness(repositories)
    harness.say(IntentName.PLAY_MUSIC, query="alpha")
    harness.say(IntentName.MUSIC_NEXT)
    harness.say(IntentName.MUSIC_NEXT)
    harness.player.finish()
    assert harness.service.current is None
    assert not harness.service.is_active
    harness.say(IntentName.MUSIC_PAUSE)
    assert harness.keys.media == [MediaKey.PLAY_PAUSE]


def test_finished_track_continues_with_recommendation(repositories: Repositories) -> None:
    radio = Track(title="Mix", artist="Radio", url="https://soundcloud.com/radio")
    harness = MusicHarness(repositories, radio=[radio])
    harness.say(IntentName.PLAY_MUSIC, query="alpha")
    harness.say(IntentName.MUSIC_NEXT)
    harness.say(IntentName.MUSIC_NEXT)
    harness.player.finish()
    assert harness.service.current == radio
    assert harness.service.is_active
