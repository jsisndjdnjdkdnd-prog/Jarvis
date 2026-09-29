from __future__ import annotations

import sqlite3
from datetime import datetime

from jarvis.core.models import CommandRecord
from jarvis.storage.db import Database, now_timestamp, to_timestamp


class CommandHistoryRepository:
    def __init__(self, database: Database) -> None:
        self._db = database

    def record(
        self,
        text: str,
        normalized: str,
        intent_json: str | None,
        stage: str | None,
        success: bool,
        reply: str,
    ) -> int:
        return self._db.insert(
            """
            INSERT INTO command_history
                (text, normalized, intent_json, stage, success, reply, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (text, normalized, intent_json, stage, int(success), reply, now_timestamp()),
        )

    def recent(self, limit: int = 50) -> list[CommandRecord]:
        rows = self._db.fetch_all(
            "SELECT * FROM command_history ORDER BY id DESC LIMIT ?", (limit,)
        )
        return [self._to_record(row) for row in rows]

    def count_since(self, moment: datetime) -> int:
        return int(
            self._db.fetch_value(
                "SELECT COUNT(*) FROM command_history WHERE created_at >= ?",
                (to_timestamp(moment),),
                default=0,
            )
        )

    def most_used_intents(self, limit: int = 10) -> list[tuple[str, int]]:
        rows = self._db.fetch_all(
            """
            SELECT json_extract(intent_json, '$.name') AS name, COUNT(*) AS total
            FROM command_history
            WHERE success = 1 AND intent_json IS NOT NULL
            GROUP BY name ORDER BY total DESC LIMIT ?
            """,
            (limit,),
        )
        return [(row["name"], int(row["total"])) for row in rows if row["name"]]

    def stage_counts(self) -> dict[str, int]:
        rows = self._db.fetch_all(
            """
            SELECT COALESCE(stage, 'unresolved') AS stage, COUNT(*) AS total
            FROM command_history GROUP BY COALESCE(stage, 'unresolved')
            """
        )
        return {str(row["stage"]): int(row["total"]) for row in rows}

    @staticmethod
    def _to_record(row: sqlite3.Row) -> CommandRecord:
        return CommandRecord(
            id=int(row["id"]),
            text=row["text"],
            normalized=row["normalized"],
            intent_json=row["intent_json"],
            stage=row["stage"],
            success=bool(row["success"]),
            reply=row["reply"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )
