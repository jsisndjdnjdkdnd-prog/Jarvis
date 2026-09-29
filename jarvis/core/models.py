from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from jarvis.core.intent import Action


class BindingSource(StrEnum):
    USER = "user"
    VOICE = "voice"
    LEARNED = "learned"
    IMPORTED = "imported"


@dataclass(frozen=True)
class Binding:
    id: int | None
    phrase: str
    normalized: str
    action: Action
    source: BindingSource = BindingSource.USER
    use_count: int = 0
    last_used_at: datetime | None = None


class AliasSource(StrEnum):
    TRAINING = "training"
    USAGE = "usage"
    MANUAL = "manual"


@dataclass(frozen=True)
class VocabularyAlias:
    id: int | None
    word_id: int
    alias: str
    normalized: str
    weight: float = 1.0
    hits: int = 0
    misses: int = 0
    source: AliasSource = AliasSource.TRAINING


@dataclass(frozen=True)
class VoiceSample:
    id: int | None
    word_id: int
    file_path: Path
    duration_seconds: float
    transcripts: tuple[str, ...] = ()
    features: bytes | None = None


@dataclass(frozen=True)
class VocabularyWord:
    id: int | None
    text: str
    normalized: str
    action: Action | None = None
    acoustic_threshold: float | None = None
    is_trained: bool = False
    aliases: tuple[VocabularyAlias, ...] = ()
    sample_count: int = 0


class ProgramKind(StrEnum):
    EXECUTABLE = "exe"
    SHORTCUT = "lnk"
    STEAM = "steam"
    EPIC = "epic"
    UWP = "uwp"
    URL = "url"
    SYSTEM = "system"
    USER = "user"


@dataclass(frozen=True)
class Program:
    id: int | None
    name: str
    normalized: str
    launch_target: str
    kind: ProgramKind
    source: str
    process_names: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    is_user_defined: bool = False


@dataclass(frozen=True)
class CommandRecord:
    id: int | None
    text: str
    normalized: str
    intent_json: str | None
    stage: str | None
    success: bool
    reply: str
    created_at: datetime


class ReminderStatus(StrEnum):
    PENDING = "pending"
    DONE = "done"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class Reminder:
    id: int | None
    message: str
    due_at: datetime
    status: ReminderStatus = ReminderStatus.PENDING
    created_at: datetime | None = None


class PreferenceKind(StrEnum):
    ARTIST = "artist"
    GENRE = "genre"
    TRACK = "track"
    APP = "app"


@dataclass(frozen=True)
class Preference:
    kind: PreferenceKind
    value: str
    weight: float


@dataclass(frozen=True)
class Track:
    title: str
    artist: str
    url: str
    duration_seconds: float | None = None
    source_id: str | None = None
    stream_url: str | None = None

    @property
    def display_name(self) -> str:
        if not self.artist:
            return self.title
        return f"{self.artist} — {self.title}"


@dataclass(frozen=True)
class PlayedTrack:
    artist: str
    title: str
    url: str
    played_at: datetime
    liked: bool = False


@dataclass(frozen=True)
class DeepSeekStats:
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    calls_today: int = 0
    cache_hits: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    average_latency_ms: float = 0.0
    learned_phrases: int = 0
    by_purpose: dict[str, int] = field(default_factory=dict)
    stage_counts: dict[str, int] = field(default_factory=dict)
