from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from jarvis.core.errors import StorageError

logger = logging.getLogger(__name__)

IN_MEMORY = ":memory:"
Params = Sequence[Any] | dict[str, Any]


class Database:
    def __init__(self, path: Path | str) -> None:
        self._path = str(path)
        self._lock = threading.RLock()
        self._connection = self._connect()

    def _connect(self) -> sqlite3.Connection:
        if self._path != IN_MEMORY:
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        try:
            connection = sqlite3.connect(
                self._path, check_same_thread=False, isolation_level=None, timeout=10
            )
        except sqlite3.Error as error:
            raise StorageError(f"Не вдалося відкрити базу {self._path}: {error}") from error
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        if self._path != IN_MEMORY:
            connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                self._connection.execute("BEGIN")
                yield self._connection
                self._connection.execute("COMMIT")
            except sqlite3.Error as error:
                self._connection.execute("ROLLBACK")
                raise StorageError(str(error)) from error
            except BaseException:
                self._connection.execute("ROLLBACK")
                raise

    def execute(self, sql: str, params: Params = ()) -> int:
        return self._run(sql, params).rowcount

    def insert(self, sql: str, params: Params = ()) -> int:
        return int(self._run(sql, params).lastrowid or 0)

    def _run(self, sql: str, params: Params) -> sqlite3.Cursor:
        with self._lock:
            try:
                return self._connection.execute(sql, params)
            except sqlite3.Error as error:
                raise StorageError(f"{error} у запиті: {sql}") from error

    def fetch_all(self, sql: str, params: Params = ()) -> list[sqlite3.Row]:
        with self._lock:
            try:
                return list(self._connection.execute(sql, params).fetchall())
            except sqlite3.Error as error:
                raise StorageError(f"{error} у запиті: {sql}") from error

    def fetch_one(self, sql: str, params: Params = ()) -> sqlite3.Row | None:
        with self._lock:
            try:
                return self._connection.execute(sql, params).fetchone()
            except sqlite3.Error as error:
                raise StorageError(f"{error} у запиті: {sql}") from error

    def fetch_value(self, sql: str, params: Params = (), default: Any = None) -> Any:
        row = self.fetch_one(sql, params)
        if row is None or row[0] is None:
            return default
        return row[0]


def to_timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat(timespec="seconds")


def from_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def now_timestamp() -> str:
    return datetime.now().isoformat(timespec="seconds")
