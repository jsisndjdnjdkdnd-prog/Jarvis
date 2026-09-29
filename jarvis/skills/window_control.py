from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from jarvis.core.context import DialogContext, SkillResult
from jarvis.core.intent import Intent, IntentName, WindowCommand
from jarvis.skills.input_control import InputController
from jarvis.skills.window_manager import WindowManager

logger = logging.getLogger(__name__)

MAX_REPEATS = 10
UNKNOWN_COMMAND_REPLY = "Не зрозумів, що зробити з вікном, сер."
EMPTY_TEXT_REPLY = "Що саме надрукувати, сер?"
UNSUPPORTED_REPLY = "Цього з вікнами я поки не вмію, сер."
UNSUPPORTED_REPLIES: dict[str, str] = {
    "close_all": "Закривати всі вікна разом я не ризикну, сер: можна втратити незбережене. Можу їх згорнути.",
}


@dataclass(frozen=True)
class Shortcut:
    combination: str
    reply: str
    repeatable: bool = False


@dataclass(frozen=True)
class WindowOperation:
    run: Callable[[], None]
    reply: str
    learnable: bool = True


SHORTCUTS: dict[WindowCommand, Shortcut] = {
    WindowCommand.MINIMIZE_ALL: Shortcut("windows+d", "Згорнув усі вікна."),
    WindowCommand.NEW_TAB: Shortcut("ctrl+t", "Нова вкладка."),
    WindowCommand.CLOSE_TAB: Shortcut("ctrl+w", "Закрив вкладку."),
    WindowCommand.REOPEN_TAB: Shortcut("ctrl+shift+t", "Повернув закриту вкладку."),
    WindowCommand.NEXT_TAB: Shortcut("ctrl+tab", "Наступна вкладка.", repeatable=True),
    WindowCommand.REFRESH: Shortcut("f5", "Оновив сторінку."),
    WindowCommand.BACK: Shortcut("alt+left", "Повернувся назад."),
    WindowCommand.FORWARD: Shortcut("alt+right", "Перейшов уперед."),
    WindowCommand.ZOOM_IN: Shortcut("ctrl+plus", "Збільшив масштаб.", repeatable=True),
    WindowCommand.ZOOM_OUT: Shortcut("ctrl+minus", "Зменшив масштаб.", repeatable=True),
    WindowCommand.SCROLL_DOWN: Shortcut("page down", "Прокрутив униз.", repeatable=True),
    WindowCommand.SCROLL_UP: Shortcut("page up", "Прокрутив угору.", repeatable=True),
    WindowCommand.FULLSCREEN: Shortcut("f11", "Перемкнув повноекранний режим."),
    WindowCommand.COPY: Shortcut("ctrl+c", "Скопіював."),
    WindowCommand.PASTE: Shortcut("ctrl+v", "Вставив."),
    WindowCommand.UNDO: Shortcut("ctrl+z", "Скасував останню дію."),
    WindowCommand.SELECT_ALL: Shortcut("ctrl+a", "Виділив усе."),
    WindowCommand.SAVE: Shortcut("ctrl+s", "Зберіг."),
}


def parse_window_command(mode: str | None) -> WindowCommand | None:
    if not mode:
        return None
    try:
        return WindowCommand(mode.strip().lower())
    except ValueError:
        return None


def repeat_count(amount: int | None) -> int:
    return max(1, min(MAX_REPEATS, amount or 1))


class WindowControlSkill:
    name = "window_control"
    intents = frozenset({IntentName.WINDOW_CONTROL, IntentName.TYPE_TEXT})

    def __init__(self, input_controller: InputController, windows: WindowManager) -> None:
        self._input = input_controller
        self._operations: dict[WindowCommand, WindowOperation] = {
            WindowCommand.MINIMIZE: WindowOperation(windows.minimize_foreground, "Згорнув вікно."),
            WindowCommand.MAXIMIZE: WindowOperation(windows.maximize_foreground, "Розгорнув вікно."),
            WindowCommand.RESTORE: WindowOperation(windows.restore_foreground, "Відновив вікно."),
            WindowCommand.CLOSE: WindowOperation(windows.close_foreground, "Закрив вікно.", learnable=False),
        }

    def handle(self, intent: Intent, context: DialogContext) -> SkillResult:
        if intent.name is IntentName.TYPE_TEXT:
            return self._type(intent)
        return self._control(intent)

    def _control(self, intent: Intent) -> SkillResult:
        command = parse_window_command(intent.mode)
        if command is None:
            logger.info("Невідома команда вікна: %s", intent.mode)
            return SkillResult(UNKNOWN_COMMAND_REPLY, success=False, learnable=False)
        operation = self._operations.get(command)
        if operation is not None:
            operation.run()
            return SkillResult(operation.reply, learnable=operation.learnable)
        if command is WindowCommand.SWITCH:
            return self._switch(repeat_count(intent.amount))
        shortcut = SHORTCUTS.get(command)
        if shortcut is None:
            return self._unsupported(command)
        return self._press(shortcut, intent.amount)

    def _switch(self, steps: int) -> SkillResult:
        self._input.send("+".join(["alt", *["tab"] * steps]))
        return SkillResult("Перемкнув вікно.")

    def _press(self, shortcut: Shortcut, amount: int | None) -> SkillResult:
        times = repeat_count(amount) if shortcut.repeatable else 1
        for _ in range(times):
            self._input.send(shortcut.combination)
        return SkillResult(shortcut.reply)

    @staticmethod
    def _unsupported(command: WindowCommand) -> SkillResult:
        logger.info("Команда вікна без обробника: %s", command.value)
        return SkillResult(UNSUPPORTED_REPLIES.get(command.value, UNSUPPORTED_REPLY), success=False, learnable=False)

    def _type(self, intent: Intent) -> SkillResult:
        text = (intent.message or "").strip()
        if not text:
            return SkillResult(EMPTY_TEXT_REPLY, success=False, learnable=False)
        self._input.write(text)
        return SkillResult("Надрукував.")
