from __future__ import annotations

import logging
from pathlib import Path

from jarvis.core.errors import ActionExecutionError, StorageError
from jarvis.core.event_bus import EventBus
from jarvis.core.events import (
    ErrorOccurred,
    ProgramAddRequested,
    ProgramDeleteRequested,
    ProgramLocationProvided,
    ProgramRescanRequested,
    ProgramsIndexed,
    ProgramsListed,
    ProgramsListRequested,
    SpeakRequested,
)
from jarvis.core.models import Program, ProgramKind
from jarvis.skills.apps.catalog import ProgramAliasBuilder, ProgramCatalog, clean_program_name
from jarvis.skills.apps.indexer import ProgramIndexer
from jarvis.skills.apps.launcher import ProgramLauncher
from jarvis.storage.repositories.programs import ProgramRepository

logger = logging.getLogger(__name__)


class ProgramsService:
    def __init__(
        self,
        bus: EventBus,
        repository: ProgramRepository,
        catalog: ProgramCatalog,
        indexer: ProgramIndexer,
        launcher: ProgramLauncher,
        alias_builder: ProgramAliasBuilder,
    ) -> None:
        self._bus = bus
        self._repository = repository
        self._catalog = catalog
        self._indexer = indexer
        self._launcher = launcher
        self._alias_builder = alias_builder

    def start(self) -> None:
        self._bus.subscribe(ProgramsListRequested, lambda _: self._bus.publish(ProgramsListed(self._catalog.all())))
        self._bus.subscribe(ProgramRescanRequested, lambda _: self._indexer.rescan_async())
        self._bus.subscribe(ProgramLocationProvided, self._on_location)
        self._bus.subscribe(ProgramAddRequested, self._on_add)
        self._bus.subscribe(ProgramDeleteRequested, self._on_delete)

    def _on_location(self, event: ProgramLocationProvided) -> None:
        if event.path is None:
            self._bus.publish(SpeakRequested("Добре, сер."))
            return
        program = self._register(event.program_name, event.path, (event.program_name,))
        if program is None:
            return
        try:
            self._launcher.launch(program)
        except ActionExecutionError as error:
            self._bus.publish(ErrorOccurred(str(error)))
            return
        self._bus.publish(SpeakRequested(f"Запам'ятав. Відкриваю {program.name}."))

    def _on_add(self, event: ProgramAddRequested) -> None:
        self._register(event.name, event.path, event.aliases)

    def _on_delete(self, event: ProgramDeleteRequested) -> None:
        if self._repository.delete(event.program_id):
            self._bus.publish(ProgramsIndexed(self._repository.count()))

    def _register(self, name: str, path: Path, aliases: tuple[str, ...]) -> Program | None:
        display_name = name.strip() or path.stem
        program = Program(
            id=None,
            name=display_name,
            normalized=clean_program_name(display_name),
            launch_target=str(path),
            kind=ProgramKind.USER,
            source="user",
            process_names=(path.name.lower(),) if path.suffix.lower() == ".exe" else (),
            is_user_defined=True,
        )
        try:
            saved = self._repository.save(program, self._alias_builder.build(display_name, (*aliases, path.stem)))
        except StorageError as error:
            self._bus.publish(ErrorOccurred(f"Не вдалося зберегти програму: {error}"))
            return None
        logger.info("Додано програму користувача %s → %s", saved.name, saved.launch_target)
        self._bus.publish(ProgramsIndexed(self._repository.count()))
        self._catalog.reload()
        return saved
