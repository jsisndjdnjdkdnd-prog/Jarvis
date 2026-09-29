from __future__ import annotations

import logging
import time
from collections.abc import Callable

from jarvis.core.context import DialogContext, SkillResult
from jarvis.core.errors import ActionExecutionError, ProgramNotFoundError, SkillError
from jarvis.core.intent import Action, ActionType, Intent
from jarvis.skills.apps.launcher import FolderResolver, UrlResolver
from jarvis.skills.apps.skill import NOT_FOUND_REPLY, ProgramService
from jarvis.skills.media_soundcloud.skill import MusicService
from jarvis.skills.platform import ShellOpener

logger = logging.getLogger(__name__)

IntentRunner = Callable[[Intent, DialogContext], SkillResult]
MAX_MACRO_DEPTH = 5


class HotkeySender:
    def send(self, combination: str) -> None:
        try:
            import keyboard
        except ImportError as error:
            raise ActionExecutionError("Бібліотека keyboard не встановлена") from error
        try:
            keyboard.send(combination)
        except ValueError as error:
            raise ActionExecutionError(f"Невідома комбінація клавіш «{combination}»") from error
        except OSError as error:
            raise ActionExecutionError(f"Гарячі клавіші недоступні: {error}") from error


class ActionExecutor:
    def __init__(
        self,
        programs: ProgramService,
        opener: ShellOpener,
        folders: FolderResolver,
        urls: UrlResolver,
        music: MusicService,
        hotkeys: HotkeySender,
        intent_runner: IntentRunner,
    ) -> None:
        self._programs = programs
        self._opener = opener
        self._folders = folders
        self._urls = urls
        self._music = music
        self._hotkeys = hotkeys
        self._intent_runner = intent_runner

    def execute(self, action: Action, context: DialogContext, depth: int = 0) -> SkillResult:
        if depth > MAX_MACRO_DEPTH:
            raise ActionExecutionError("Занадто глибока вкладеність макросів")
        if action.delay_seconds > 0:
            time.sleep(min(action.delay_seconds, 30.0))
        handlers: dict[ActionType, Callable[[Action, DialogContext, int], SkillResult]] = {
            ActionType.OPEN_APP: self._open_app,
            ActionType.LAUNCH: self._launch,
            ActionType.CLOSE_PROCESS: self._close,
            ActionType.OPEN_FOLDER: self._open_folder,
            ActionType.SHELL: self._shell,
            ActionType.HOTKEY: self._hotkey,
            ActionType.PLAY_TRACK: self._play,
            ActionType.MACRO: self._macro,
            ActionType.INTENT: self._intent,
        }
        return handlers[action.type](action, context, depth)

    def _open_app(self, action: Action, context: DialogContext, depth: int) -> SkillResult:
        try:
            program = self._programs.open(action.target, context)
        except ProgramNotFoundError:
            self._programs.request_location(action.target)
            return SkillResult(NOT_FOUND_REPLY, success=False)
        return SkillResult(f"Відкриваю {program.name}.")

    def _launch(self, action: Action, context: DialogContext, depth: int) -> SkillResult:
        target = action.target.strip()
        if not ShellOpener.looks_like_url(target) and not ShellOpener.looks_like_path(target):
            target = self._urls.resolve(target) if "." in target else target
        self._opener.open(target)
        return SkillResult("Запускаю.")

    def _close(self, action: Action, context: DialogContext, depth: int) -> SkillResult:
        closed = self._programs.close(action.target or None, context)
        return SkillResult(f"{closed} закрито.")

    def _open_folder(self, action: Action, context: DialogContext, depth: int) -> SkillResult:
        folder = self._folders.resolve(action.target)
        if folder is None:
            raise ActionExecutionError(f"Папку «{action.target}» не знайдено")
        self._opener.open(str(folder))
        return SkillResult(f"Відкриваю {folder.name or 'папку'}.")

    def _shell(self, action: Action, context: DialogContext, depth: int) -> SkillResult:
        self._opener.run_shell(action.target)
        return SkillResult("Команду виконано.")

    def _hotkey(self, action: Action, context: DialogContext, depth: int) -> SkillResult:
        self._hotkeys.send(action.target)
        return SkillResult("Натиснув.")

    def _play(self, action: Action, context: DialogContext, depth: int) -> SkillResult:
        track = self._music.play_query(action.target)
        context.remember_track(track)
        return SkillResult(f"Вмикаю {track.display_name}.")

    def _intent(self, action: Action, context: DialogContext, depth: int) -> SkillResult:
        if action.intent is None:
            raise ActionExecutionError("Бінд без інтенту")
        return self._intent_runner(action.intent, context)

    def _macro(self, action: Action, context: DialogContext, depth: int) -> SkillResult:
        replies: list[str] = []
        success = True
        for step in action.steps:
            result = self._run_step(step, context, depth + 1)
            success = success and result.success
            if not result.success:
                replies.append(result.reply)
        if not replies:
            return SkillResult("Виконано, сер.", success=success)
        return SkillResult(" ".join(replies), success=success)

    def _run_step(self, step: Action, context: DialogContext, depth: int) -> SkillResult:
        try:
            return self.execute(step, context, depth)
        except SkillError as error:
            logger.warning("Крок макросу %s не вдався: %s", step.describe(), error)
            return SkillResult(str(error), success=False)
