from __future__ import annotations

import logging

from jarvis.core.context import DialogContext, SkillResult
from jarvis.core.errors import ProgramNotFoundError, SkillError
from jarvis.core.event_bus import EventBus
from jarvis.core.events import ProgramLocationRequested
from jarvis.core.intent import Intent, IntentName
from jarvis.core.models import Program
from jarvis.skills.apps.catalog import ProgramCatalog
from jarvis.skills.apps.indexer import ProgramIndexer
from jarvis.skills.apps.launcher import FolderResolver, ProcessCloser, ProgramLauncher, UrlResolver
from jarvis.skills.platform import ShellOpener

logger = logging.getLogger(__name__)

NOT_FOUND_REPLY = "Не знайшов такої програми. Покажете, де вона?"


class ProgramService:
    def __init__(
        self,
        catalog: ProgramCatalog,
        launcher: ProgramLauncher,
        closer: ProcessCloser,
        bus: EventBus,
    ) -> None:
        self._catalog = catalog
        self._launcher = launcher
        self._closer = closer
        self._bus = bus

    def open(self, name: str, context: DialogContext) -> Program:
        program = self._catalog.find(name)
        if program is None:
            raise ProgramNotFoundError(name)
        self._launcher.launch(program)
        context.remember_program(program)
        return program

    def close(self, name: str | None, context: DialogContext) -> str:
        if name is None:
            return self._close_last(context)
        program = self._catalog.find(name)
        if program is not None:
            report = self._closer.close_program(program)
            if report.total:
                context.forget_program(program)
                return program.name
        report = self._closer.close_by_query(name)
        if report.total:
            return name
        raise SkillError(f"Не бачу запущеної програми «{name}», сер.")

    def _close_last(self, context: DialogContext) -> str:
        program = context.last_program
        if program is None:
            raise SkillError("Не зрозумів, що саме закрити, сер.")
        report = self._closer.close_program(program)
        context.forget_program(program)
        if not report.total:
            raise SkillError(f"{program.name} вже не запущено.")
        return program.name

    def request_location(self, name: str) -> None:
        self._bus.publish(ProgramLocationRequested(name))


class AppsSkill:
    name = "apps"
    intents = frozenset(
        {
            IntentName.OPEN_APP,
            IntentName.CLOSE_APP,
            IntentName.OPEN_FOLDER,
            IntentName.OPEN_URL,
            IntentName.RESCAN_PROGRAMS,
        }
    )

    def __init__(
        self,
        programs: ProgramService,
        indexer: ProgramIndexer,
        folders: FolderResolver,
        urls: UrlResolver,
        opener: ShellOpener,
    ) -> None:
        self._programs = programs
        self._indexer = indexer
        self._folders = folders
        self._urls = urls
        self._opener = opener

    def handle(self, intent: Intent, context: DialogContext) -> SkillResult:
        handlers = {
            IntentName.OPEN_APP: self._open_app,
            IntentName.CLOSE_APP: self._close_app,
            IntentName.OPEN_FOLDER: self._open_folder,
            IntentName.OPEN_URL: self._open_url,
            IntentName.RESCAN_PROGRAMS: self._rescan,
        }
        return handlers[intent.name](intent, context)

    def _open_app(self, intent: Intent, context: DialogContext) -> SkillResult:
        target = (intent.target or "").strip()
        if not target:
            return SkillResult("Що саме відкрити, сер?", success=False)
        if "." in target and " " not in target:
            return self._open_url(intent, context)
        try:
            program = self._programs.open(target, context)
        except ProgramNotFoundError:
            self._programs.request_location(target)
            return SkillResult(NOT_FOUND_REPLY, success=False, learnable=False)
        return SkillResult(f"Відкриваю {program.name}.")

    def _close_app(self, intent: Intent, context: DialogContext) -> SkillResult:
        closed = self._programs.close(intent.target, context)
        return SkillResult(f"{closed} закрито.")

    def _open_folder(self, intent: Intent, context: DialogContext) -> SkillResult:
        folder = self._folders.resolve(intent.target or "")
        if folder is None:
            return SkillResult("Не знайшов такої папки, сер.", success=False)
        self._opener.open(str(folder))
        return SkillResult(f"Відкриваю {folder.name or 'домашню папку'}.")

    def _open_url(self, intent: Intent, context: DialogContext) -> SkillResult:
        url = self._urls.resolve(intent.target or "")
        self._opener.open(url)
        return SkillResult("Відкриваю сайт.")

    def _rescan(self, intent: Intent, context: DialogContext) -> SkillResult:
        self._indexer.rescan_async()
        return SkillResult("Оновлюю список програм, сер.", learnable=False)
