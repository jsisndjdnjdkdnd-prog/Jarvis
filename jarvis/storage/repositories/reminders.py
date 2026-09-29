from __future__ import annotations

import sqlite3
from datetime import datetime

from jarvis.core.errors import StorageError
from jarvis.core.models import Reminder, ReminderStatus
from jarvis.storage.db import Database, from_timestamp, now_timestamp, to_timestamp


class ReminderRepository:
    def __init__(self, database: Database) -> None:
        self._db = database

    def add(self, message: str, due_at: datetime) -> Reminder:
        reminder_id = self._db.insert(
            "INSERT INTO reminders (message, due_at, status, created_at) VALUES (?, ?, ?, ?)",
            (message, to_timestamp(due_at), ReminderStatus.PENDING.value, now_timestamp()),
        )
        reminder = self.get(reminder_id)
        if reminder is None:
            raise StorageError("Нагадування не збережено")
        return reminder

    def get(self, reminder_id: int) -> Reminder | None:
        row = self._db.fetch_one("SELECT * FROM reminders WHERE id = ?", (reminder_id,))
        return self._to_reminder(row) if row is not None else None

    def pending(self) -> list[Reminder]:
        rows = self._db.fetch_all(
            "SELECT * FROM reminders WHERE status = ? ORDER BY due_at",
            (ReminderStatus.PENDING.value,),
        )
        return [self._to_reminder(row) for row in rows]

    def due(self, moment: datetime) -> list[Reminder]:
        rows = self._db.fetch_all(
            "SELECT * FROM reminders WHERE status = ? AND due_at <= ? ORDER BY due_at",
            (ReminderStatus.PENDING.value, to_timestamp(moment)),
        )
        return [self._to_reminder(row) for row in rows]

    def set_status(self, reminder_id: int, status: ReminderStatus) -> bool:
        return (
            self._db.execute(
                "UPDATE reminders SET status = ?, notified_at = ? WHERE id = ?",
                (status.value, now_timestamp(), reminder_id),
            )
            > 0
        )

    @staticmethod
    def _to_reminder(row: sqlite3.Row) -> Reminder:
        due_at = from_timestamp(row["due_at"])
        if due_at is None:
            raise StorageError(f"Нагадування {row['id']} без часу")
        return Reminder(
            id=int(row["id"]),
            message=row["message"],
            due_at=due_at,
            status=ReminderStatus(row["status"]),
            created_at=from_timestamp(row["created_at"]),
        )
