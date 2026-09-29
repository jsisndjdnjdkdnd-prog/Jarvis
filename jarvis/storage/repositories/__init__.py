from __future__ import annotations

from dataclasses import dataclass

from jarvis.storage.db import Database
from jarvis.storage.repositories.bindings import BindingRepository
from jarvis.storage.repositories.deepseek import DeepSeekCacheRepository, DeepSeekStatsRepository
from jarvis.storage.repositories.history import CommandHistoryRepository
from jarvis.storage.repositories.preferences import ListeningHistoryRepository, PreferenceRepository
from jarvis.storage.repositories.programs import ProgramRepository
from jarvis.storage.repositories.reminders import ReminderRepository
from jarvis.storage.repositories.vocabulary import VocabularyRepository


@dataclass(frozen=True)
class Repositories:
    bindings: BindingRepository
    vocabulary: VocabularyRepository
    programs: ProgramRepository
    history: CommandHistoryRepository
    deepseek_cache: DeepSeekCacheRepository
    deepseek_stats: DeepSeekStatsRepository
    preferences: PreferenceRepository
    listening: ListeningHistoryRepository
    reminders: ReminderRepository

    @classmethod
    def create(cls, database: Database) -> Repositories:
        return cls(
            bindings=BindingRepository(database),
            vocabulary=VocabularyRepository(database),
            programs=ProgramRepository(database),
            history=CommandHistoryRepository(database),
            deepseek_cache=DeepSeekCacheRepository(database),
            deepseek_stats=DeepSeekStatsRepository(database),
            preferences=PreferenceRepository(database),
            listening=ListeningHistoryRepository(database),
            reminders=ReminderRepository(database),
        )


__all__ = [
    "BindingRepository",
    "CommandHistoryRepository",
    "DeepSeekCacheRepository",
    "DeepSeekStatsRepository",
    "ListeningHistoryRepository",
    "PreferenceRepository",
    "ProgramRepository",
    "ReminderRepository",
    "Repositories",
    "VocabularyRepository",
]
