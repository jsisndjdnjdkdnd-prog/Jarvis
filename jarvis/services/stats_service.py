from __future__ import annotations

import logging

from jarvis.core.errors import StorageError
from jarvis.core.event_bus import EventBus
from jarvis.core.events import BindingsChanged, CommandHandled, DeepSeekStatsChanged, DeepSeekStatsRequested
from jarvis.core.models import BindingSource
from jarvis.storage.repositories.bindings import BindingRepository
from jarvis.storage.repositories.deepseek import DeepSeekCacheRepository, DeepSeekStatsRepository
from jarvis.storage.repositories.history import CommandHistoryRepository

logger = logging.getLogger(__name__)


class DeepSeekStatsService:
    def __init__(
        self,
        bus: EventBus,
        stats: DeepSeekStatsRepository,
        cache: DeepSeekCacheRepository,
        bindings: BindingRepository,
        history: CommandHistoryRepository,
    ) -> None:
        self._bus = bus
        self._stats = stats
        self._cache = cache
        self._bindings = bindings
        self._history = history

    def start(self) -> None:
        self._bus.subscribe(DeepSeekStatsRequested, lambda _: self.publish())
        self._bus.subscribe(BindingsChanged, lambda _: self.publish())
        self._bus.subscribe(CommandHandled, lambda _: self.publish())

    def publish(self) -> None:
        try:
            snapshot = self._stats.snapshot(
                cache_hits=self._cache.total_hits(),
                learned_phrases=self._bindings.count_by_source(BindingSource.LEARNED),
                stage_counts=self._history.stage_counts(),
            )
        except StorageError:
            logger.exception("Не вдалося зібрати статистику DeepSeek")
            return
        self._bus.publish(DeepSeekStatsChanged(snapshot))
