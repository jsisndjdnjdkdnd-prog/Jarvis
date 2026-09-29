from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import BaseModel, ValidationError

from jarvis.core.errors import StorageError
from jarvis.core.event_bus import EventBus
from jarvis.core.events import (
    BindingDeleteRequested,
    BindingSaveRequested,
    BindingsChanged,
    BindingsExportRequested,
    BindingsImportRequested,
    BindingsListed,
    BindingsListRequested,
    ErrorOccurred,
    NotificationRequested,
)
from jarvis.core.intent import Action
from jarvis.core.models import Binding, BindingSource
from jarvis.nlu.text_normalizer import TextNormalizer
from jarvis.storage.repositories.bindings import BindingRepository

logger = logging.getLogger(__name__)


class BindingRecord(BaseModel):
    phrase: str
    action: Action
    source: BindingSource = BindingSource.IMPORTED


class BindingsService:
    def __init__(self, bus: EventBus, repository: BindingRepository, normalizer: TextNormalizer) -> None:
        self._bus = bus
        self._repository = repository
        self._normalizer = normalizer

    def start(self) -> None:
        self._bus.subscribe(BindingsListRequested, lambda _: self._publish_list())
        self._bus.subscribe(BindingSaveRequested, self._save)
        self._bus.subscribe(BindingDeleteRequested, self._delete)
        self._bus.subscribe(BindingsImportRequested, self._import)
        self._bus.subscribe(BindingsExportRequested, self._export)

    def _publish_list(self) -> None:
        self._bus.publish(BindingsListed(tuple(self._repository.list_all())))

    def _save(self, event: BindingSaveRequested) -> None:
        normalized = self._normalizer.normalize(event.phrase)
        if not normalized:
            self._bus.publish(ErrorOccurred("Фраза бінду порожня"))
            return
        binding = Binding(id=event.binding_id, phrase=event.phrase.strip(), normalized=normalized, action=event.action)
        try:
            self._repository.save(binding)
        except StorageError as error:
            self._bus.publish(ErrorOccurred(f"Не вдалося зберегти бінд: {error}"))
            return
        self._bus.publish(BindingsChanged())

    def _delete(self, event: BindingDeleteRequested) -> None:
        if self._repository.delete(event.binding_id):
            self._bus.publish(BindingsChanged())

    def _import(self, event: BindingsImportRequested) -> None:
        try:
            records = self._read(event.path)
        except (OSError, json.JSONDecodeError, ValidationError) as error:
            self._bus.publish(ErrorOccurred(f"Не вдалося імпортувати {event.path.name}: {error}"))
            return
        for record in records:
            normalized = self._normalizer.normalize(record.phrase)
            if normalized:
                self._repository.save(
                    Binding(id=None, phrase=record.phrase, normalized=normalized, action=record.action, source=record.source)
                )
        self._bus.publish(BindingsChanged())
        self._bus.publish(NotificationRequested("Бінди", f"Імпортовано: {len(records)}"))

    def _export(self, event: BindingsExportRequested) -> None:
        records = [
            BindingRecord(phrase=binding.phrase, action=binding.action, source=binding.source).model_dump(mode="json")
            for binding in self._repository.list_all()
        ]
        try:
            event.path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as error:
            self._bus.publish(ErrorOccurred(f"Не вдалося експортувати: {error}"))
            return
        self._bus.publish(NotificationRequested("Бінди", f"Експортовано: {len(records)}"))

    @staticmethod
    def _read(path: Path) -> list[BindingRecord]:
        data = json.loads(path.read_text(encoding="utf-8"))
        items = data if isinstance(data, list) else data.get("bindings", [])
        return [BindingRecord.model_validate(item) for item in items]
