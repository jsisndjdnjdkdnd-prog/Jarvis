from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from jarvis.core.context import DialogContext, SkillResult
from jarvis.core.errors import SkillError
from jarvis.core.intent import Intent, IntentName, YouTubeCommand
from jarvis.skills.formatting import format_duration_accusative
from jarvis.skills.input_control import InputController
from jarvis.skills.window_manager import WindowManager

logger = logging.getLogger(__name__)

FOCUS_SETTLE_SECONDS = 0.25
DEFAULT_SEEK_SECONDS = 10
LONG_SEEK_SECONDS = 10
SHORT_SEEK_SECONDS = 5
MAX_SEEK_SECONDS = 600
UNKNOWN_COMMAND_REPLY = "Не зрозумів, що зробити з відео, сер."
NO_WINDOW_REPLY = "Не бачу відкритого YouTube, сер."
UNSUPPORTED_REPLY = "Цього з відео я поки не вмію, сер."


@dataclass(frozen=True)
class VideoShortcut:
    combination: str
    reply: str


@dataclass(frozen=True)
class SeekKeys:
    long_key: str
    short_key: str
    direction: str


@dataclass(frozen=True)
class SeekPlan:
    long_presses: int
    short_presses: int

    @property
    def seconds(self) -> int:
        return self.long_presses * LONG_SEEK_SECONDS + self.short_presses * SHORT_SEEK_SECONDS


SHORTCUTS: dict[YouTubeCommand, VideoShortcut] = {
    YouTubeCommand.TOGGLE: VideoShortcut("k", "Перемкнув відтворення."),
    YouTubeCommand.PAUSE: VideoShortcut("k", "Пауза."),
    YouTubeCommand.PLAY: VideoShortcut("k", "Продовжую."),
    YouTubeCommand.SUBTITLES: VideoShortcut("c", "Субтитри перемкнув."),
    YouTubeCommand.FULLSCREEN: VideoShortcut("f", "Повноекранний режим перемкнув."),
    YouTubeCommand.MUTE: VideoShortcut("m", "Звук відео перемкнув."),
    YouTubeCommand.THEATER: VideoShortcut("t", "Режим кінотеатру перемкнув."),
    YouTubeCommand.NEXT: VideoShortcut("shift+n", "Наступне відео."),
    YouTubeCommand.PREVIOUS: VideoShortcut("shift+p", "Попереднє відео."),
    YouTubeCommand.FASTER: VideoShortcut("shift+period", "Пришвидшив відтворення."),
    YouTubeCommand.SLOWER: VideoShortcut("shift+comma", "Сповільнив відтворення."),
}

SEEK_KEYS: dict[YouTubeCommand, SeekKeys] = {
    YouTubeCommand.FORWARD: SeekKeys("l", "right", "вперед"),
    YouTubeCommand.BACKWARD: SeekKeys("j", "left", "назад"),
}


def parse_youtube_command(mode: str | None) -> YouTubeCommand | None:
    if not mode:
        return None
    try:
        return YouTubeCommand(mode.strip().lower())
    except ValueError:
        return None


def plan_seek(seconds: int) -> SeekPlan:
    bounded = max(0, min(MAX_SEEK_SECONDS, seconds))
    long_presses, remainder = divmod(bounded, LONG_SEEK_SECONDS)
    short_presses = 1 if remainder >= SHORT_SEEK_SECONDS or long_presses == 0 else 0
    return SeekPlan(long_presses, short_presses)


class YouTubeControlSkill:
    name = "youtube_control"
    intents = frozenset({IntentName.YOUTUBE_CONTROL})

    def __init__(
        self,
        input_controller: InputController,
        windows: WindowManager,
        title_keywords: tuple[str, ...] = ("YouTube",),
        settle: Callable[[float], None] = time.sleep,
    ) -> None:
        self._input = input_controller
        self._windows = windows
        self._title_keywords = title_keywords
        self._settle = settle

    def handle(self, intent: Intent, context: DialogContext) -> SkillResult:
        command = parse_youtube_command(intent.mode)
        if command is None:
            logger.info("Невідома команда YouTube: %s", intent.mode)
            return SkillResult(UNKNOWN_COMMAND_REPLY, success=False, learnable=False)
        action = self._action(command, intent)
        if action is None:
            logger.info("Команда YouTube без обробника: %s", command.value)
            return SkillResult(UNSUPPORTED_REPLY, success=False, learnable=False)
        self._activate_player()
        return action()

    def _action(self, command: YouTubeCommand, intent: Intent) -> Callable[[], SkillResult] | None:
        seek = SEEK_KEYS.get(command)
        if seek is not None:
            return lambda: self._seek(seek, self._seek_seconds(intent))
        shortcut = SHORTCUTS.get(command)
        if shortcut is not None:
            return lambda: self._press(shortcut)
        return None

    def _activate_player(self) -> None:
        handle = self._windows.find(self._title_keywords)
        if handle is None:
            raise SkillError(NO_WINDOW_REPLY)
        if not self._windows.focus(handle):
            logger.info("Вікно YouTube не стало активним, пробую все одно")
        self._settle(FOCUS_SETTLE_SECONDS)

    def _press(self, shortcut: VideoShortcut) -> SkillResult:
        self._input.send(shortcut.combination)
        return SkillResult(shortcut.reply)

    def _seek(self, keys: SeekKeys, seconds: int) -> SkillResult:
        plan = plan_seek(seconds)
        for _ in range(plan.long_presses):
            self._input.send(keys.long_key)
        for _ in range(plan.short_presses):
            self._input.send(keys.short_key)
        return SkillResult(f"Перемотав на {format_duration_accusative(plan.seconds)} {keys.direction}.")

    @staticmethod
    def _seek_seconds(intent: Intent) -> int:
        if intent.duration_seconds:
            return intent.duration_seconds
        if intent.amount:
            return intent.amount
        return DEFAULT_SEEK_SECONDS
