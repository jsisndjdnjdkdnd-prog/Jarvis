from __future__ import annotations

import sqlite3
from dataclasses import replace

from pydantic import ValidationError

from jarvis.core.errors import StorageError
from jarvis.core.intent import Action
from jarvis.core.models import Binding, BindingSource
from jarvis.storage.db import Database, from_timestamp, now_timestamp


class BindingRepository:
    def __init__(self, database: Database) -> None:
        self._db = database

    def list_all(self) -> list[Binding]:
        rows = self._db.fetch_all("SELECT * FROM bindings ORDER BY phrase COLLATE NOCASE")
        return [self._to_binding(row) for row in rows]

    def get(self, binding_id: int) -> Binding | None:
        row = self._db.fetch_one("SELECT * FROM bindings WHERE id = ?", (binding_id,))
        return self._to_binding(row) if row is not None else None

    def find_by_normalized(self, normalized: str) -> Binding | None:
        row = self._db.fetch_one("SELECT * FROM bindings WHERE normalized = ?", (normalized,))
        return self._to_binding(row) if row is not None else None

    def save(self, binding: Binding) -> Binding:
        if binding.id is not None:
            return self._update(binding)
        existing = self.find_by_normalized(binding.normalized)
        if existing is not None:
            return self._update(replace(binding, id=existing.id))
        return self._insert(binding)

    def delete(self, binding_id: int) -> bool:
        return self._db.execute("DELETE FROM bindings WHERE id = ?", (binding_id,)) > 0

    def mark_used(self, binding_id: int) -> None:
        self._db.execute(
            "UPDATE bindings SET use_count = use_count + 1, last_used_at = ? WHERE id = ?",
            (now_timestamp(), binding_id),
        )

    def count_by_source(self, source: BindingSource) -> int:
        return int(
            self._db.fetch_value(
                "SELECT COUNT(*) FROM bindings WHERE source = ?", (source.value,), default=0
            )
        )

    def _insert(self, binding: Binding) -> Binding:
        timestamp = now_timestamp()
        new_id = self._db.insert(
            """
            INSERT INTO bindings (phrase, normalized, action_json, source, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                binding.phrase,
                binding.normalized,
                binding.action.model_dump_json(),
                binding.source.value,
                timestamp,
                timestamp,
            ),
        )
        return self._require(new_id)

    def _update(self, binding: Binding) -> Binding:
        if binding.id is None:
            raise StorageError("Неможливо оновити бінд без id")
        self._db.execute(
            """
            UPDATE bindings
            SET phrase = ?, normalized = ?, action_json = ?, source = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                binding.phrase,
                binding.normalized,
                binding.action.model_dump_json(),
                binding.source.value,
                now_timestamp(),
                binding.id,
            ),
        )
        return self._require(binding.id)

    def _require(self, binding_id: int) -> Binding:
        binding = self.get(binding_id)
        if binding is None:
            raise StorageError(f"Бінд {binding_id} не знайдено після збереження")
        return binding

    @staticmethod
    def _to_binding(row: sqlite3.Row) -> Binding:
        try:
            action = Action.model_validate_json(row["action_json"])
        except ValidationError as error:
            raise StorageError(f"Пошкоджена дія бінду {row['id']}: {error}") from error
        return Binding(
            id=int(row["id"]),
            phrase=row["phrase"],
            normalized=row["normalized"],
            action=action,
            source=BindingSource(row["source"]),
            use_count=int(row["use_count"]),
            last_used_at=from_timestamp(row["last_used_at"]),
        )
