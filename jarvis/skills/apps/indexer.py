from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterable, Sequence
from datetime import datetime, timedelta

from jarvis.core.errors import JarvisError
from jarvis.core.models import Program, ProgramKind
from jarvis.skills.apps.catalog import ProgramAliasBuilder, clean_program_name
from jarvis.skills.apps.sources import DiscoveredProgram, ProgramSource
from jarvis.storage.repositories.programs import ProgramRepository

logger = logging.getLogger(__name__)

KIND_PRIORITY: dict[ProgramKind, int] = {
    ProgramKind.USER: 0,
    ProgramKind.STEAM: 1,
    ProgramKind.EPIC: 1,
    ProgramKind.SYSTEM: 2,
    ProgramKind.SHORTCUT: 3,
    ProgramKind.UWP: 4,
    ProgramKind.URL: 5,
    ProgramKind.EXECUTABLE: 6,
}


class ProgramIndexer:
    def __init__(
        self,
        sources: Sequence[ProgramSource],
        repository: ProgramRepository,
        alias_builder: ProgramAliasBuilder,
        on_indexed: Callable[[int], None],
        com_initializer: Callable[[], Callable[[], None]] | None = None,
    ) -> None:
        self._sources = tuple(sources)
        self._repository = repository
        self._alias_builder = alias_builder
        self._on_indexed = on_indexed
        self._com_initializer = com_initializer
        self._lock = threading.Lock()

    def needs_rescan(self, max_age_hours: float) -> bool:
        last = self._repository.last_indexed_at()
        if last is None:
            return True
        return datetime.now() - last > timedelta(hours=max_age_hours)

    def rescan_async(self) -> None:
        threading.Thread(target=self.rescan, name="program-indexer", daemon=True).start()

    def rescan(self) -> int:
        if not self._lock.acquire(blocking=False):
            logger.info("Індексація вже виконується")
            return 0
        release_com = self._com_initializer() if self._com_initializer else None
        try:
            count = self._index()
        finally:
            if release_com is not None:
                release_com()
            self._lock.release()
        self._on_indexed(count)
        return count

    def _index(self) -> int:
        discovered: list[DiscoveredProgram] = []
        for source in self._sources:
            discovered.extend(self._collect(source))
        merged = self._merge(discovered)
        count = self._repository.replace_indexed(
            (program, self._alias_builder.build(program.name, program.aliases)) for program in merged
        )
        logger.info("Проіндексовано програм: %d", count)
        return count

    @staticmethod
    def _collect(source: ProgramSource) -> list[DiscoveredProgram]:
        try:
            items = list(source.discover())
        except (OSError, JarvisError, ImportError, ValueError) as error:
            logger.warning("Джерело програм %s недоступне: %s", source.name, error)
            return []
        logger.info("Джерело %s: %d програм", source.name, len(items))
        return items

    def _merge(self, discovered: Iterable[DiscoveredProgram]) -> list[Program]:
        grouped: dict[str, list[DiscoveredProgram]] = {}
        for item in discovered:
            key = clean_program_name(item.name)
            if key:
                grouped.setdefault(key, []).append(item)
        return [self._combine(key, items) for key, items in grouped.items()]

    @staticmethod
    def _combine(key: str, items: list[DiscoveredProgram]) -> Program:
        ordered = sorted(items, key=lambda item: KIND_PRIORITY.get(item.kind, 9))
        primary = ordered[0]
        process_names = tuple(dict.fromkeys(name for item in ordered for name in item.process_names))
        aliases = tuple(dict.fromkeys(alias for item in ordered for alias in item.aliases))
        return Program(
            id=None,
            name=primary.name,
            normalized=key,
            launch_target=primary.launch_target,
            kind=primary.kind,
            source=primary.source,
            process_names=process_names,
            aliases=aliases,
        )
