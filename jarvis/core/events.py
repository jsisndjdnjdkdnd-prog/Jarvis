from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jarvis.core.intent import Action
from jarvis.core.models import (
    Binding,
    DeepSeekStats,
    Program,
    Reminder,
    Track,
    VocabularyAlias,
    VocabularyWord,
    VoiceSample,
)
from jarvis.core.speech_types import AssistantState, CommandSource, Utterance


@dataclass(frozen=True)
class Event:
    pass


@dataclass(frozen=True)
class AssistantStateChanged(Event):
    state: AssistantState


@dataclass(frozen=True)
class CommandReceived(Event):
    text: str
    source: CommandSource
    utterance: Utterance | None = None


@dataclass(frozen=True)
class CommandHandled(Event):
    text: str
    reply: str
    intent_name: str | None
    stage: str | None
    success: bool


@dataclass(frozen=True)
class AssistantReplied(Event):
    text: str
    success: bool = True


@dataclass(frozen=True)
class SpeakRequested(Event):
    text: str


@dataclass(frozen=True)
class SpeechStarted(Event):
    text: str


@dataclass(frozen=True)
class SpeechFinished(Event):
    text: str


@dataclass(frozen=True)
class WakeWordDetected(Event):
    phrase: str


@dataclass(frozen=True)
class ListenRequested(Event):
    follow_up: bool = False


@dataclass(frozen=True)
class ConversationEnded(Event):
    pass


@dataclass(frozen=True)
class ListeningModeChanged(Event):
    always_listen: bool


@dataclass(frozen=True)
class SpeechInterruptRequested(Event):
    pass


@dataclass(frozen=True)
class ListenerPauseRequested(Event):
    paused: bool
    reason: str


@dataclass(frozen=True)
class MicLevelChanged(Event):
    level: float


@dataclass(frozen=True)
class CorrectionRequested(Event):
    pass


@dataclass(frozen=True)
class ShutdownRequested(Event):
    pass


@dataclass(frozen=True)
class ShowWindowRequested(Event):
    pass


@dataclass(frozen=True)
class HideWindowRequested(Event):
    pass


@dataclass(frozen=True)
class HudToggleRequested(Event):
    pass


@dataclass(frozen=True)
class ErrorOccurred(Event):
    message: str


@dataclass(frozen=True)
class NotificationRequested(Event):
    title: str
    message: str


@dataclass(frozen=True)
class BindingsListRequested(Event):
    pass


@dataclass(frozen=True)
class BindingsListed(Event):
    bindings: tuple[Binding, ...]


@dataclass(frozen=True)
class BindingsChanged(Event):
    pass


@dataclass(frozen=True)
class BindingSaveRequested(Event):
    binding_id: int | None
    phrase: str
    action: Action


@dataclass(frozen=True)
class BindingDeleteRequested(Event):
    binding_id: int


@dataclass(frozen=True)
class BindingsImportRequested(Event):
    path: Path


@dataclass(frozen=True)
class BindingsExportRequested(Event):
    path: Path


@dataclass(frozen=True)
class VocabularyListRequested(Event):
    pass


@dataclass(frozen=True)
class VocabularyListed(Event):
    words: tuple[VocabularyWord, ...]


@dataclass(frozen=True)
class VocabularyChanged(Event):
    pass


@dataclass(frozen=True)
class VocabularyWordDeleteRequested(Event):
    word_id: int


@dataclass(frozen=True)
class ProgramsListRequested(Event):
    pass


@dataclass(frozen=True)
class ProgramsListed(Event):
    programs: tuple[Program, ...]


@dataclass(frozen=True)
class ProgramsIndexed(Event):
    count: int


@dataclass(frozen=True)
class ProgramRescanRequested(Event):
    pass


@dataclass(frozen=True)
class ProgramLocationRequested(Event):
    program_name: str


@dataclass(frozen=True)
class ProgramLocationProvided(Event):
    program_name: str
    path: Path | None


@dataclass(frozen=True)
class ProgramAddRequested(Event):
    name: str
    path: Path
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProgramDeleteRequested(Event):
    program_id: int


@dataclass(frozen=True)
class RemindersListRequested(Event):
    pass


@dataclass(frozen=True)
class RemindersListed(Event):
    reminders: tuple[Reminder, ...]


@dataclass(frozen=True)
class RemindersChanged(Event):
    pass


@dataclass(frozen=True)
class ReminderCancelRequested(Event):
    reminder_id: int


@dataclass(frozen=True)
class ReminderDue(Event):
    reminder: Reminder


@dataclass(frozen=True)
class TimerFinished(Event):
    label: str


@dataclass(frozen=True)
class DeepSeekStatsRequested(Event):
    pass


@dataclass(frozen=True)
class DeepSeekStatsChanged(Event):
    stats: DeepSeekStats


@dataclass(frozen=True)
class NowPlayingChanged(Event):
    track: Track | None


@dataclass(frozen=True)
class RegionSelectionRequested(Event):
    request_id: str
    preview_path: Path


@dataclass(frozen=True)
class RegionSelected(Event):
    request_id: str
    fraction: tuple[float, float, float, float] | None


@dataclass(frozen=True)
class SettingsSnapshotRequested(Event):
    pass


@dataclass(frozen=True)
class SettingsSnapshot(Event):
    values: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SettingsUpdateRequested(Event):
    changes: dict[str, Any]


@dataclass(frozen=True)
class SettingsSaved(Event):
    message: str


@dataclass(frozen=True)
class VocabularyWordAddRequested(Event):
    text: str
    action: Action | None = None


@dataclass(frozen=True)
class TrainingStartRequested(Event):
    word_id: int


@dataclass(frozen=True)
class TrainingSessionStarted(Event):
    word: VocabularyWord
    samples: tuple[VoiceSample, ...]


@dataclass(frozen=True)
class TrainingSampleRequested(Event):
    word_id: int


@dataclass(frozen=True)
class TrainingRecordingStarted(Event):
    word_id: int


@dataclass(frozen=True)
class TrainingSamplesChanged(Event):
    word_id: int
    samples: tuple[VoiceSample, ...]


@dataclass(frozen=True)
class TrainingSampleDeleteRequested(Event):
    word_id: int
    sample_id: int


@dataclass(frozen=True)
class TrainingFinishRequested(Event):
    word_id: int


@dataclass(frozen=True)
class TrainingModelBuilt(Event):
    word_id: int
    aliases: tuple[VocabularyAlias, ...]
    threshold: float


@dataclass(frozen=True)
class TrainingTestRequested(Event):
    word_id: int


@dataclass(frozen=True)
class TrainingTestResult(Event):
    word_id: int
    transcript: str
    alias_score: float
    acoustic_score: float | None
    combined_score: float
    matched: bool


@dataclass(frozen=True)
class TrainingSaveRequested(Event):
    word_id: int


@dataclass(frozen=True)
class TrainingSaved(Event):
    word_id: int


@dataclass(frozen=True)
class TrainingSessionClosed(Event):
    word_id: int


@dataclass(frozen=True)
class TrainingFailed(Event):
    word_id: int | None
    reason: str
