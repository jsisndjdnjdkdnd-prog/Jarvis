from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import datetime

from jarvis.core.errors import StorageError
from jarvis.core.models import Program, ProgramKind
from jarvis.storage.db import Database, from_timestamp, now_timestamp


class ProgramRepository:
    def __init__(self, database: Database) -> None:
        self._db = database

    def list_all(self) -> list[Program]:
        rows = self._db.fetch_all("SELECT * FROM programs ORDER BY name COLLATE NOCASE")
        aliases = self._aliases_by_program()
        return [self._to_program(row, aliases.get(int(row["id"]), ())) for row in rows]

    def get(self, program_id: int) -> Program | None:
        row = self._db.fetch_one("SELECT * FROM programs WHERE id = ?", (program_id,))
        if row is None:
            return None
        return self._to_program(row, tuple(self._aliases_for(program_id)))

    def count(self) -> int:
        return int(self._db.fetch_value("SELECT COUNT(*) FROM programs", default=0))

    def last_indexed_at(self) -> datetime | None:
        value = self._db.fetch_value(
            "SELECT MAX(updated_at) FROM programs WHERE is_user_defined = 0"
        )
        return from_timestamp(value)

    def save(self, program: Program, alias_normalizer: dict[str, str]) -> Program:
        with self._db.transaction() as connection:
            program_id = self._upsert(connection, program)
            self._store_aliases(connection, program_id, alias_normalizer)
        stored = self.get(program_id)
        if stored is None:
            raise StorageError(f"Програму «{program.name}» не збережено")
        return stored

    def replace_indexed(
        self, programs: Iterable[tuple[Program, dict[str, str]]]
    ) -> int:
        count = 0
        with self._db.transaction() as connection:
            connection.execute("DELETE FROM programs WHERE is_user_defined = 0")
            for program, aliases in programs:
                program_id = self._upsert(connection, program)
                self._store_aliases(connection, program_id, aliases)
                count += 1
        return count

    def add_alias(self, program_id: int, alias: str, normalized: str) -> None:
        self._db.execute(
            """
            INSERT INTO program_aliases (program_id, alias, normalized) VALUES (?, ?, ?)
            ON CONFLICT (program_id, normalized) DO NOTHING
            """,
            (program_id, alias, normalized),
        )

    def delete(self, program_id: int) -> bool:
        return self._db.execute("DELETE FROM programs WHERE id = ?", (program_id,)) > 0

    @staticmethod
    def _upsert(connection: sqlite3.Connection, program: Program) -> int:
        connection.execute(
            """
            INSERT INTO programs
                (name, normalized, launch_target, kind, source, process_names_json,
                 is_user_defined, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (normalized, launch_target) DO UPDATE SET
                name = excluded.name,
                kind = excluded.kind,
                source = excluded.source,
                process_names_json = excluded.process_names_json,
                is_user_defined = MAX(programs.is_user_defined, excluded.is_user_defined),
                updated_at = excluded.updated_at
            """,
            (
                program.name,
                program.normalized,
                program.launch_target,
                program.kind.value,
                program.source,
                json.dumps(list(program.process_names), ensure_ascii=False),
                int(program.is_user_defined),
                now_timestamp(),
            ),
        )
        row = connection.execute(
            "SELECT id FROM programs WHERE normalized = ? AND launch_target = ?",
            (program.normalized, program.launch_target),
        ).fetchone()
        return int(row["id"])

    @staticmethod
    def _store_aliases(
        connection: sqlite3.Connection, program_id: int, aliases: dict[str, str]
    ) -> None:
        for alias, normalized in aliases.items():
            connection.execute(
                """
                INSERT INTO program_aliases (program_id, alias, normalized) VALUES (?, ?, ?)
                ON CONFLICT (program_id, normalized) DO NOTHING
                """,
                (program_id, alias, normalized),
            )

    def _aliases_for(self, program_id: int) -> list[str]:
        rows = self._db.fetch_all(
            "SELECT normalized FROM program_aliases WHERE program_id = ?", (program_id,)
        )
        return [row["normalized"] for row in rows]

    def _aliases_by_program(self) -> dict[int, tuple[str, ...]]:
        grouped: dict[int, list[str]] = {}
        for row in self._db.fetch_all("SELECT program_id, normalized FROM program_aliases"):
            grouped.setdefault(int(row["program_id"]), []).append(row["normalized"])
        return {program_id: tuple(values) for program_id, values in grouped.items()}

    @staticmethod
    def _to_program(row: sqlite3.Row, aliases: Iterable[str]) -> Program:
        return Program(
            id=int(row["id"]),
            name=row["name"],
            normalized=row["normalized"],
            launch_target=row["launch_target"],
            kind=ProgramKind(row["kind"]),
            source=row["source"],
            process_names=tuple(json.loads(row["process_names_json"] or "[]")),
            aliases=tuple(aliases),
            is_user_defined=bool(row["is_user_defined"]),
        )
