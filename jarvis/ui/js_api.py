from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Protocol

from pydantic import ValidationError

from jarvis.core.event_bus import EventBus
from jarvis.core.events import (
    BindingDeleteRequested,
    BindingSaveRequested,
    BindingsExportRequested,
    BindingsImportRequested,
    BindingsListRequested,
    CommandReceived,
    CorrectionRequested,
    DeepSeekStatsRequested,
    Event,
    HideWindowRequested,
    HudToggleRequested,
    ListenRequested,
    ProgramAddRequested,
    ProgramDeleteRequested,
    ProgramLocationProvided,
    ProgramRescanRequested,
    ProgramsListRequested,
    RegionSelected,
    ReminderCancelRequested,
    RemindersListRequested,
    SettingsSnapshotRequested,
    SettingsUpdateRequested,
    ShowWindowRequested,
    ShutdownRequested,
    TrainingFinishRequested,
    TrainingSampleDeleteRequested,
    TrainingSampleRequested,
    TrainingSaveRequested,
    TrainingSessionClosed,
    TrainingStartRequested,
    TrainingTestRequested,
    VocabularyListRequested,
    VocabularyWordAddRequested,
    VocabularyWordDeleteRequested,
)
from jarvis.core.intent import Action
from jarvis.core.speech_types import CommandSource

logger = logging.getLogger(__name__)

PROGRAM_FILE_TYPES: tuple[str, ...] = ("Програми (*.exe;*.lnk;*.bat;*.url)", "Усі файли (*.*)")
JSON_FILE_TYPES: tuple[str, ...] = ("JSON (*.json)",)
ANY_FILE_TYPES: tuple[str, ...] = ("Усі файли (*.*)",)
Result = dict[str, Any]


class NativeDialogs(Protocol):
    def open_file(self, file_types: tuple[str, ...]) -> Path | None: ...

    def save_file(self, default_name: str, file_types: tuple[str, ...]) -> Path | None: ...

    def choose_folder(self) -> Path | None: ...


def ok(**payload: Any) -> Result:
    return {"ok": True, **payload}


def failure(message: str) -> Result:
    return {"ok": False, "error": message}


class JarvisApi:
    def __init__(self, bus: EventBus, dialogs: NativeDialogs) -> None:
        self._bus = bus
        self._dialogs = dialogs

    def _emit(self, event: Event) -> Result:
        self._bus.publish(event)
        return ok()

    def bootstrap(self) -> Result:
        for event in (
            SettingsSnapshotRequested(),
            BindingsListRequested(),
            VocabularyListRequested(),
            ProgramsListRequested(),
            RemindersListRequested(),
            DeepSeekStatsRequested(),
        ):
            self._bus.publish(event)
        return ok()

    def send_command(self, text: str) -> Result:
        cleaned = str(text or "").strip()
        if not cleaned:
            return failure("Порожня команда")
        return self._emit(CommandReceived(cleaned, CommandSource.TEXT))

    def listen(self) -> Result:
        return self._emit(ListenRequested())

    def correction(self) -> Result:
        return self._emit(CorrectionRequested())

    def save_binding(self, binding_id: int | None, phrase: str, action: dict[str, Any]) -> Result:
        if not str(phrase or "").strip():
            return failure("Введіть фразу")
        try:
            parsed = Action.model_validate(action)
        except ValidationError as error:
            return failure(f"Некоректна дія: {error.errors()[0].get('msg', error)}")
        return self._emit(BindingSaveRequested(binding_id, str(phrase).strip(), parsed))

    def delete_binding(self, binding_id: int) -> Result:
        return self._emit(BindingDeleteRequested(int(binding_id)))

    def import_bindings(self) -> Result:
        path = self._dialogs.open_file(JSON_FILE_TYPES)
        return self._emit(BindingsImportRequested(path)) if path else ok(cancelled=True)

    def export_bindings(self) -> Result:
        path = self._dialogs.save_file("jarvis-bindings.json", JSON_FILE_TYPES)
        return self._emit(BindingsExportRequested(path)) if path else ok(cancelled=True)

    def browse_file(self) -> Result:
        path = self._dialogs.open_file(ANY_FILE_TYPES)
        return ok(path=str(path) if path else None)

    def browse_folder(self) -> Result:
        path = self._dialogs.choose_folder()
        return ok(path=str(path) if path else None)

    def add_word(self, text: str, action: dict[str, Any] | None) -> Result:
        if not str(text or "").strip():
            return failure("Введіть слово")
        parsed = None
        if action:
            try:
                parsed = Action.model_validate(action)
            except ValidationError as error:
                return failure(f"Некоректна дія: {error.errors()[0].get('msg', error)}")
        return self._emit(VocabularyWordAddRequested(str(text).strip(), parsed))

    def start_training(self, word_id: int) -> Result:
        return self._emit(TrainingStartRequested(int(word_id)))

    def record_sample(self, word_id: int) -> Result:
        return self._emit(TrainingSampleRequested(int(word_id)))

    def delete_sample(self, word_id: int, sample_id: int) -> Result:
        return self._emit(TrainingSampleDeleteRequested(int(word_id), int(sample_id)))

    def finish_training(self, word_id: int) -> Result:
        return self._emit(TrainingFinishRequested(int(word_id)))

    def test_word(self, word_id: int) -> Result:
        return self._emit(TrainingTestRequested(int(word_id)))

    def save_word(self, word_id: int) -> Result:
        return self._emit(TrainingSaveRequested(int(word_id)))

    def close_training(self, word_id: int) -> Result:
        return self._emit(TrainingSessionClosed(int(word_id)))

    def delete_word(self, word_id: int) -> Result:
        return self._emit(VocabularyWordDeleteRequested(int(word_id)))

    def rescan_programs(self) -> Result:
        return self._emit(ProgramRescanRequested())

    def add_program(self, name: str) -> Result:
        path = self._dialogs.open_file(PROGRAM_FILE_TYPES)
        if path is None:
            return ok(cancelled=True)
        spoken = str(name or "").strip() or path.stem
        return self._emit(ProgramAddRequested(spoken, path, (spoken,)))

    def delete_program(self, program_id: int) -> Result:
        return self._emit(ProgramDeleteRequested(int(program_id)))

    def locate_program(self, name: str) -> Result:
        path = self._dialogs.open_file(PROGRAM_FILE_TYPES)
        return self._emit(ProgramLocationProvided(str(name), path))

    def skip_program(self, name: str) -> Result:
        return self._emit(ProgramLocationProvided(str(name), None))

    def cancel_reminder(self, reminder_id: int) -> Result:
        return self._emit(ReminderCancelRequested(int(reminder_id)))

    def request_settings(self) -> Result:
        return self._emit(SettingsSnapshotRequested())

    def save_settings(self, changes: dict[str, Any]) -> Result:
        if not isinstance(changes, dict):
            return failure("Некоректні налаштування")
        return self._emit(SettingsUpdateRequested(changes))

    def refresh_stats(self) -> Result:
        return self._emit(DeepSeekStatsRequested())

    def toggle_hud(self) -> Result:
        return self._emit(HudToggleRequested())

    def show_main(self) -> Result:
        return self._emit(ShowWindowRequested())

    def hide_main(self) -> Result:
        return self._emit(HideWindowRequested())

    def quit(self) -> Result:
        return self._emit(ShutdownRequested())

    def region_selected(self, request_id: str, fraction: list[float] | None) -> Result:
        if fraction is None or len(fraction) != 4:
            return self._emit(RegionSelected(str(request_id), None))
        left, top, right, bottom = (float(value) for value in fraction)
        return self._emit(RegionSelected(str(request_id), (left, top, right, bottom)))
