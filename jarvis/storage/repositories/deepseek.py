from __future__ import annotations

from datetime import datetime

from jarvis.core.models import DeepSeekStats
from jarvis.storage.db import Database, now_timestamp, to_timestamp


class DeepSeekCacheRepository:
    def __init__(self, database: Database) -> None:
        self._db = database

    def get(self, normalized: str) -> str | None:
        row = self._db.fetch_one(
            "SELECT intent_json FROM deepseek_cache WHERE normalized = ?", (normalized,)
        )
        if row is None:
            return None
        self._db.execute(
            "UPDATE deepseek_cache SET hits = hits + 1 WHERE normalized = ?", (normalized,)
        )
        return str(row["intent_json"])

    def put(self, normalized: str, intent_json: str) -> None:
        self._db.execute(
            """
            INSERT INTO deepseek_cache (normalized, intent_json, created_at) VALUES (?, ?, ?)
            ON CONFLICT (normalized) DO UPDATE SET intent_json = excluded.intent_json
            """,
            (normalized, intent_json, now_timestamp()),
        )

    def delete(self, normalized: str) -> None:
        self._db.execute("DELETE FROM deepseek_cache WHERE normalized = ?", (normalized,))

    def total_hits(self) -> int:
        return int(self._db.fetch_value("SELECT SUM(hits) FROM deepseek_cache", default=0))


class DeepSeekStatsRepository:
    def __init__(self, database: Database) -> None:
        self._db = database

    def record_call(
        self,
        purpose: str,
        success: bool,
        latency_ms: float,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> None:
        self._db.insert(
            """
            INSERT INTO deepseek_calls
                (purpose, success, latency_ms, prompt_tokens, completion_tokens, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (purpose, int(success), latency_ms, prompt_tokens, completion_tokens, now_timestamp()),
        )

    def snapshot(
        self, cache_hits: int, learned_phrases: int, stage_counts: dict[str, int] | None = None
    ) -> DeepSeekStats:
        row = self._db.fetch_one(
            """
            SELECT COUNT(*) AS total,
                   COALESCE(SUM(success), 0) AS ok,
                   COALESCE(SUM(prompt_tokens), 0) AS prompt,
                   COALESCE(SUM(completion_tokens), 0) AS completion,
                   COALESCE(AVG(latency_ms), 0) AS latency
            FROM deepseek_calls
            """
        )
        start_of_day = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today = int(
            self._db.fetch_value(
                "SELECT COUNT(*) FROM deepseek_calls WHERE created_at >= ?",
                (to_timestamp(start_of_day),),
                default=0,
            )
        )
        purposes = {
            str(item["purpose"]): int(item["total"])
            for item in self._db.fetch_all(
                "SELECT purpose, COUNT(*) AS total FROM deepseek_calls GROUP BY purpose"
            )
        }
        total = int(row["total"]) if row is not None else 0
        successful = int(row["ok"]) if row is not None else 0
        return DeepSeekStats(
            total_calls=total,
            successful_calls=successful,
            failed_calls=total - successful,
            calls_today=today,
            cache_hits=cache_hits,
            prompt_tokens=int(row["prompt"]) if row is not None else 0,
            completion_tokens=int(row["completion"]) if row is not None else 0,
            average_latency_ms=float(row["latency"]) if row is not None else 0.0,
            learned_phrases=learned_phrases,
            by_purpose=purposes,
            stage_counts=dict(stage_counts or {}),
        )
