from __future__ import annotations

import logging
from dataclasses import dataclass

from jarvis.storage.db import Database

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Migration:
    version: int
    statements: tuple[str, ...]


MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        version=1,
        statements=(
            """
            CREATE TABLE bindings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phrase TEXT NOT NULL,
                normalized TEXT NOT NULL UNIQUE,
                action_json TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'user',
                use_count INTEGER NOT NULL DEFAULT 0,
                last_used_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE vocabulary_words (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                normalized TEXT NOT NULL UNIQUE,
                action_json TEXT,
                acoustic_threshold REAL,
                is_trained INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE vocabulary_aliases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                word_id INTEGER NOT NULL REFERENCES vocabulary_words(id) ON DELETE CASCADE,
                alias TEXT NOT NULL,
                normalized TEXT NOT NULL,
                weight REAL NOT NULL DEFAULT 1.0,
                hits INTEGER NOT NULL DEFAULT 0,
                misses INTEGER NOT NULL DEFAULT 0,
                source TEXT NOT NULL DEFAULT 'training',
                created_at TEXT NOT NULL,
                UNIQUE (word_id, normalized)
            )
            """,
            """
            CREATE TABLE voice_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                word_id INTEGER NOT NULL REFERENCES vocabulary_words(id) ON DELETE CASCADE,
                file_path TEXT NOT NULL,
                duration_seconds REAL NOT NULL,
                transcripts_json TEXT NOT NULL DEFAULT '[]',
                features BLOB,
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE programs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                normalized TEXT NOT NULL,
                launch_target TEXT NOT NULL,
                kind TEXT NOT NULL,
                source TEXT NOT NULL,
                process_names_json TEXT NOT NULL DEFAULT '[]',
                is_user_defined INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                UNIQUE (normalized, launch_target)
            )
            """,
            """
            CREATE TABLE program_aliases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                program_id INTEGER NOT NULL REFERENCES programs(id) ON DELETE CASCADE,
                alias TEXT NOT NULL,
                normalized TEXT NOT NULL,
                UNIQUE (program_id, normalized)
            )
            """,
            """
            CREATE TABLE command_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                normalized TEXT NOT NULL,
                intent_json TEXT,
                stage TEXT,
                success INTEGER NOT NULL,
                reply TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE deepseek_cache (
                normalized TEXT PRIMARY KEY,
                intent_json TEXT NOT NULL,
                hits INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE deepseek_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                purpose TEXT NOT NULL,
                success INTEGER NOT NULL,
                latency_ms REAL NOT NULL,
                prompt_tokens INTEGER NOT NULL DEFAULT 0,
                completion_tokens INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE preferences (
                kind TEXT NOT NULL,
                value TEXT NOT NULL,
                normalized TEXT NOT NULL,
                weight REAL NOT NULL DEFAULT 1.0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (kind, normalized)
            )
            """,
            """
            CREATE TABLE listening_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                artist TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                liked INTEGER NOT NULL DEFAULT 0,
                played_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message TEXT NOT NULL,
                due_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                notified_at TEXT
            )
            """,
            "CREATE INDEX idx_aliases_word ON vocabulary_aliases(word_id)",
            "CREATE INDEX idx_samples_word ON voice_samples(word_id)",
            "CREATE INDEX idx_program_aliases_program ON program_aliases(program_id)",
            "CREATE INDEX idx_history_created ON command_history(created_at)",
            "CREATE INDEX idx_reminders_due ON reminders(status, due_at)",
            "CREATE INDEX idx_listening_played ON listening_history(played_at)",
        ),
    ),
)


class Migrator:
    def __init__(self, database: Database, migrations: tuple[Migration, ...] = MIGRATIONS) -> None:
        self._database = database
        self._migrations = tuple(sorted(migrations, key=lambda migration: migration.version))

    def current_version(self) -> int:
        return int(self._database.fetch_value("PRAGMA user_version", default=0))

    def migrate(self) -> int:
        version = self.current_version()
        for migration in self._migrations:
            if migration.version <= version:
                continue
            self._apply(migration)
            version = migration.version
        return version

    def _apply(self, migration: Migration) -> None:
        with self._database.transaction() as connection:
            for statement in migration.statements:
                connection.execute(statement)
            connection.execute(f"PRAGMA user_version = {int(migration.version)}")
        logger.info("Застосовано міграцію БД v%d", migration.version)
