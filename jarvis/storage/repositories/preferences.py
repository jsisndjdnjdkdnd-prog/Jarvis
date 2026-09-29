from __future__ import annotations

from datetime import datetime

from jarvis.core.models import PlayedTrack, Preference, PreferenceKind
from jarvis.storage.db import Database, now_timestamp


class PreferenceRepository:
    def __init__(self, database: Database) -> None:
        self._db = database

    def bump(self, kind: PreferenceKind, value: str, amount: float = 1.0) -> None:
        normalized = value.strip().lower()
        if not normalized:
            return
        self._db.execute(
            """
            INSERT INTO preferences (kind, value, normalized, weight, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (kind, normalized) DO UPDATE SET
                weight = preferences.weight + excluded.weight,
                updated_at = excluded.updated_at
            """,
            (kind.value, value.strip(), normalized, amount, now_timestamp()),
        )

    def top(self, kind: PreferenceKind, limit: int = 10) -> list[Preference]:
        rows = self._db.fetch_all(
            "SELECT * FROM preferences WHERE kind = ? ORDER BY weight DESC LIMIT ?",
            (kind.value, limit),
        )
        return [
            Preference(kind=PreferenceKind(row["kind"]), value=row["value"], weight=float(row["weight"]))
            for row in rows
        ]


class ListeningHistoryRepository:
    def __init__(self, database: Database) -> None:
        self._db = database

    def record(self, artist: str, title: str, url: str) -> int:
        return self._db.insert(
            "INSERT INTO listening_history (artist, title, url, played_at) VALUES (?, ?, ?, ?)",
            (artist, title, url, now_timestamp()),
        )

    def mark_liked(self, url: str) -> None:
        self._db.execute("UPDATE listening_history SET liked = 1 WHERE url = ?", (url,))

    def recent(self, limit: int) -> list[PlayedTrack]:
        rows = self._db.fetch_all(
            "SELECT * FROM listening_history ORDER BY id DESC LIMIT ?", (limit,)
        )
        return [
            PlayedTrack(
                artist=row["artist"],
                title=row["title"],
                url=row["url"],
                played_at=datetime.fromisoformat(row["played_at"]),
                liked=bool(row["liked"]),
            )
            for row in rows
        ]
