from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from pydantic import ValidationError

from jarvis.core.errors import StorageError
from jarvis.core.intent import Action
from jarvis.core.models import AliasSource, VocabularyAlias, VocabularyWord, VoiceSample
from jarvis.storage.db import Database, now_timestamp


class VocabularyRepository:
    def __init__(self, database: Database) -> None:
        self._db = database

    def list_words(self) -> list[VocabularyWord]:
        rows = self._db.fetch_all("SELECT * FROM vocabulary_words ORDER BY text COLLATE NOCASE")
        return [self._to_word(row) for row in rows]

    def get_word(self, word_id: int) -> VocabularyWord | None:
        row = self._db.fetch_one("SELECT * FROM vocabulary_words WHERE id = ?", (word_id,))
        return self._to_word(row) if row is not None else None

    def find_word(self, normalized: str) -> VocabularyWord | None:
        row = self._db.fetch_one(
            "SELECT * FROM vocabulary_words WHERE normalized = ?", (normalized,)
        )
        return self._to_word(row) if row is not None else None

    def add_word(self, text: str, normalized: str, action: Action | None) -> VocabularyWord:
        existing = self.find_word(normalized)
        if existing is not None:
            return existing
        timestamp = now_timestamp()
        word_id = self._db.insert(
            """
            INSERT INTO vocabulary_words (text, normalized, action_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (text, normalized, action.model_dump_json() if action else None, timestamp, timestamp),
        )
        return self._require_word(word_id)

    def delete_word(self, word_id: int) -> bool:
        return self._db.execute("DELETE FROM vocabulary_words WHERE id = ?", (word_id,)) > 0

    def mark_trained(self, word_id: int, threshold: float | None, trained: bool) -> None:
        self._db.execute(
            """
            UPDATE vocabulary_words
            SET acoustic_threshold = ?, is_trained = ?, updated_at = ?
            WHERE id = ?
            """,
            (threshold, int(trained), now_timestamp(), word_id),
        )

    def list_aliases(self, word_id: int | None = None) -> list[VocabularyAlias]:
        if word_id is None:
            rows = self._db.fetch_all("SELECT * FROM vocabulary_aliases")
        else:
            rows = self._db.fetch_all(
                "SELECT * FROM vocabulary_aliases WHERE word_id = ?", (word_id,)
            )
        return [self._to_alias(row) for row in rows]

    def upsert_alias(
        self, word_id: int, alias: str, normalized: str, source: AliasSource
    ) -> VocabularyAlias:
        self._db.execute(
            """
            INSERT INTO vocabulary_aliases (word_id, alias, normalized, source, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (word_id, normalized) DO NOTHING
            """,
            (word_id, alias, normalized, source.value, now_timestamp()),
        )
        row = self._db.fetch_one(
            "SELECT * FROM vocabulary_aliases WHERE word_id = ? AND normalized = ?",
            (word_id, normalized),
        )
        if row is None:
            raise StorageError(f"Аліас «{alias}» не збережено")
        return self._to_alias(row)

    def reinforce_alias(self, alias_id: int, reward: float) -> None:
        self._db.execute(
            """
            UPDATE vocabulary_aliases
            SET hits = hits + 1, weight = MIN(1.0, weight + ?)
            WHERE id = ?
            """,
            (reward, alias_id),
        )

    def penalize_alias(self, alias_id: int, penalty: float, min_weight: float) -> bool:
        self._db.execute(
            """
            UPDATE vocabulary_aliases
            SET misses = misses + 1, weight = MAX(0.0, weight - ?)
            WHERE id = ?
            """,
            (penalty, alias_id),
        )
        removed = self._db.execute(
            "DELETE FROM vocabulary_aliases WHERE id = ? AND weight < ? AND source != ?",
            (alias_id, min_weight, AliasSource.MANUAL.value),
        )
        return removed > 0

    def delete_alias(self, alias_id: int) -> bool:
        return self._db.execute("DELETE FROM vocabulary_aliases WHERE id = ?", (alias_id,)) > 0

    def add_sample(
        self,
        word_id: int,
        file_path: Path,
        duration_seconds: float,
        transcripts: tuple[str, ...],
        features: bytes | None,
    ) -> VoiceSample:
        sample_id = self._db.insert(
            """
            INSERT INTO voice_samples
                (word_id, file_path, duration_seconds, transcripts_json, features, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                word_id,
                str(file_path),
                duration_seconds,
                json.dumps(list(transcripts), ensure_ascii=False),
                features,
                now_timestamp(),
            ),
        )
        sample = self.get_sample(sample_id)
        if sample is None:
            raise StorageError("Зразок не збережено")
        return sample

    def get_sample(self, sample_id: int) -> VoiceSample | None:
        row = self._db.fetch_one("SELECT * FROM voice_samples WHERE id = ?", (sample_id,))
        return self._to_sample(row) if row is not None else None

    def list_samples(self, word_id: int) -> list[VoiceSample]:
        rows = self._db.fetch_all(
            "SELECT * FROM voice_samples WHERE word_id = ? ORDER BY id", (word_id,)
        )
        return [self._to_sample(row) for row in rows]

    def update_sample_features(self, sample_id: int, features: bytes) -> None:
        self._db.execute(
            "UPDATE voice_samples SET features = ? WHERE id = ?", (features, sample_id)
        )

    def delete_sample(self, sample_id: int) -> VoiceSample | None:
        sample = self.get_sample(sample_id)
        if sample is None:
            return None
        self._db.execute("DELETE FROM voice_samples WHERE id = ?", (sample_id,))
        return sample

    def _require_word(self, word_id: int) -> VocabularyWord:
        word = self.get_word(word_id)
        if word is None:
            raise StorageError(f"Слово {word_id} не знайдено")
        return word

    def _to_word(self, row: sqlite3.Row) -> VocabularyWord:
        word_id = int(row["id"])
        sample_count = int(
            self._db.fetch_value(
                "SELECT COUNT(*) FROM voice_samples WHERE word_id = ?", (word_id,), default=0
            )
        )
        return VocabularyWord(
            id=word_id,
            text=row["text"],
            normalized=row["normalized"],
            action=self._parse_action(row["action_json"]),
            acoustic_threshold=row["acoustic_threshold"],
            is_trained=bool(row["is_trained"]),
            aliases=tuple(self.list_aliases(word_id)),
            sample_count=sample_count,
        )

    @staticmethod
    def _parse_action(raw: str | None) -> Action | None:
        if not raw:
            return None
        try:
            return Action.model_validate_json(raw)
        except ValidationError as error:
            raise StorageError(f"Пошкоджена дія слова: {error}") from error

    @staticmethod
    def _to_alias(row: sqlite3.Row) -> VocabularyAlias:
        return VocabularyAlias(
            id=int(row["id"]),
            word_id=int(row["word_id"]),
            alias=row["alias"],
            normalized=row["normalized"],
            weight=float(row["weight"]),
            hits=int(row["hits"]),
            misses=int(row["misses"]),
            source=AliasSource(row["source"]),
        )

    @staticmethod
    def _to_sample(row: sqlite3.Row) -> VoiceSample:
        return VoiceSample(
            id=int(row["id"]),
            word_id=int(row["word_id"]),
            file_path=Path(row["file_path"]),
            duration_seconds=float(row["duration_seconds"]),
            transcripts=tuple(json.loads(row["transcripts_json"] or "[]")),
            features=row["features"],
        )
