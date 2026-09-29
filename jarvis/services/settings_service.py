from __future__ import annotations

from jarvis.core.config import ConfigRepository
from jarvis.core.errors import ConfigError
from jarvis.core.event_bus import EventBus
from jarvis.core.events import (
    ErrorOccurred,
    SettingsSaved,
    SettingsSnapshot,
    SettingsSnapshotRequested,
    SettingsUpdateRequested,
)

RESTART_NOTICE = "Налаштування збережено. Частина змін застосується після перезапуску."


class SettingsService:
    def __init__(self, bus: EventBus, repository: ConfigRepository) -> None:
        self._bus = bus
        self._repository = repository

    def start(self) -> None:
        self._bus.subscribe(SettingsSnapshotRequested, lambda _: self._publish_snapshot())
        self._bus.subscribe(SettingsUpdateRequested, self._update)

    def _publish_snapshot(self) -> None:
        try:
            config = self._repository.load()
        except ConfigError as error:
            self._bus.publish(ErrorOccurred(str(error)))
            return
        self._bus.publish(SettingsSnapshot(config.model_dump(mode="json")))

    def _update(self, event: SettingsUpdateRequested) -> None:
        try:
            config = self._repository.update(event.changes)
        except ConfigError as error:
            self._bus.publish(ErrorOccurred(str(error)))
            return
        self._bus.publish(SettingsSnapshot(config.model_dump(mode="json")))
        self._bus.publish(SettingsSaved(RESTART_NOTICE))
