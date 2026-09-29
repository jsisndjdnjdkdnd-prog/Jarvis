from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable, Iterable
from typing import Any

from jarvis.core.event_bus import EventBus
from jarvis.core.events import (
    AssistantStateChanged,
    BindingsListed,
    CommandHandled,
    DeepSeekStatsChanged,
    ErrorOccurred,
    Event,
    MicLevelChanged,
    NowPlayingChanged,
    ProgramLocationRequested,
    ProgramsIndexed,
    ProgramsListed,
    ReminderDue,
    RemindersListed,
    SettingsSaved,
    SettingsSnapshot,
    SpeechFinished,
    SpeechStarted,
    TimerFinished,
    TrainingFailed,
    TrainingModelBuilt,
    TrainingRecordingStarted,
    TrainingSamplesChanged,
    TrainingSaved,
    TrainingSessionStarted,
    TrainingTestResult,
    VocabularyListed,
    WakeWordDetected,
)
from jarvis.ui.serialization import encode_batch, event_message

logger = logging.getLogger(__name__)

FLUSH_INTERVAL_SECONDS = 0.05
MAX_BATCH = 400
BatchSink = Callable[[str], None]

MAIN_WINDOW_EVENTS: tuple[type[Event], ...] = (
    AssistantStateChanged,
    CommandHandled,
    MicLevelChanged,
    WakeWordDetected,
    SpeechStarted,
    SpeechFinished,
    ErrorOccurred,
    SettingsSaved,
    SettingsSnapshot,
    TimerFinished,
    ReminderDue,
    NowPlayingChanged,
    ProgramLocationRequested,
    BindingsListed,
    VocabularyListed,
    ProgramsListed,
    ProgramsIndexed,
    RemindersListed,
    DeepSeekStatsChanged,
    TrainingSessionStarted,
    TrainingSamplesChanged,
    TrainingRecordingStarted,
    TrainingModelBuilt,
    TrainingTestResult,
    TrainingSaved,
    TrainingFailed,
)

HUD_EVENTS: tuple[type[Event], ...] = (
    AssistantStateChanged,
    MicLevelChanged,
    WakeWordDetected,
    SpeechStarted,
    CommandHandled,
)


class EventRelay:
    def __init__(
        self,
        bus: EventBus,
        event_types: Iterable[type[Event]],
        sink: BatchSink,
        ready: threading.Event,
        name: str,
    ) -> None:
        self._bus = bus
        self._event_types = tuple(event_types)
        self._sink = sink
        self._ready = ready
        self._name = name
        self._queue: queue.Queue[Event] = queue.Queue()
        self._running = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        for event_type in self._event_types:
            self._bus.subscribe(event_type, self._queue.put)
        self._running.set()
        self._thread = threading.Thread(target=self._run, name=f"ui-relay-{self._name}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running.clear()

    def _run(self) -> None:
        while self._running.is_set() and not self._ready.wait(timeout=0.5):
            continue
        while self._running.is_set():
            batch = self._collect()
            if batch:
                self._deliver(batch)

    def _collect(self) -> list[dict[str, Any]]:
        try:
            first = self._queue.get(timeout=FLUSH_INTERVAL_SECONDS)
        except queue.Empty:
            return []
        batch = [event_message(first)]
        while len(batch) < MAX_BATCH:
            try:
                batch.append(event_message(self._queue.get_nowait()))
            except queue.Empty:
                break
        return self._compact(batch)

    @staticmethod
    def _compact(batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
        levels = [message for message in batch if message["type"] == MicLevelChanged.__name__]
        if len(levels) <= 1:
            return batch
        others = [message for message in batch if message["type"] != MicLevelChanged.__name__]
        return [*others, levels[-1]]

    def _deliver(self, batch: list[dict[str, Any]]) -> None:
        try:
            self._sink(encode_batch(batch))
        except Exception:
            logger.exception("Не вдалося передати події у вікно %s", self._name)
