from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime

import pytest

from jarvis.nlu.intent_parser import IntentParser
from jarvis.nlu.text_normalizer import TextNormalizer
from jarvis.nlu.time_parser import NaturalTimeParser
from jarvis.storage.db import Database
from jarvis.storage.migrations import Migrator
from jarvis.storage.repositories import Repositories

FIXED_NOW = datetime(2026, 9, 29, 14, 0)


class StubProgramProbe:
    def __init__(self, known: set[str]) -> None:
        self._known = known

    def is_known_program(self, name: str) -> bool:
        return name in self._known


@pytest.fixture
def now() -> datetime:
    return FIXED_NOW


@pytest.fixture
def time_parser() -> NaturalTimeParser:
    return NaturalTimeParser(clock=lambda: FIXED_NOW, use_dateparser=False)


@pytest.fixture
def parser(time_parser: NaturalTimeParser) -> IntentParser:
    return IntentParser(time_parser, StubProgramProbe({"хром", "діскорд", "discord"}))


@pytest.fixture
def normalizer() -> TextNormalizer:
    return TextNormalizer(wake_words=["джарвіс", "джарвис", "jarvis"])


@pytest.fixture
def database() -> Iterator[Database]:
    db = Database(":memory:")
    Migrator(db).migrate()
    yield db
    db.close()


@pytest.fixture
def repositories(database: Database) -> Repositories:
    return Repositories.create(database)
