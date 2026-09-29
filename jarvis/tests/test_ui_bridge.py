from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path

import pytest

from jarvis.core.event_bus import EventBus
from jarvis.core.events import (
    BindingSaveRequested,
    CommandReceived,
    Event,
    MicLevelChanged,
    ProgramAddRequested,
    ProgramLocationProvided,
    RegionSelected,
    SpeakRequested,
    TrainingSamplesChanged,
    VocabularyWordAddRequested,
)
from jarvis.core.intent import ActionType
from jarvis.core.models import VoiceSample
from jarvis.core.speech_types import CommandSource
from jarvis.skills.screenshots import fraction_to_box
from jarvis.ui.event_relay import EventRelay
from jarvis.ui.js_api import JarvisApi
from jarvis.ui.serialization import encode_batch, event_message, to_jsonable
from jarvis.ui.web_assets import WebAssets


class FakeDialogs:
    def __init__(self, path: Path | None) -> None:
        self._path = path

    def open_file(self, file_types: tuple[str, ...]) -> Path | None:
        return self._path

    def save_file(self, default_name: str, file_types: tuple[str, ...]) -> Path | None:
        return self._path

    def choose_folder(self) -> Path | None:
        return self._path


class RecordingBus(EventBus):
    def __init__(self) -> None:
        super().__init__()
        self.published: list[Event] = []

    def publish(self, event: Event) -> None:
        self.published.append(event)


def test_serialization_drops_binary_and_converts_types() -> None:
    sample = VoiceSample(1, 2, Path("data/voice/2/a.wav"), 1.25, ("мал вер байтс",), b"\x00\x01")
    message = event_message(TrainingSamplesChanged(2, (sample,)))
    assert message["type"] == "TrainingSamplesChanged"
    stored = message["data"]["samples"][0]
    assert stored["features"] is None
    assert stored["file_path"].endswith("a.wav")
    assert stored["transcripts"] == ["мал вер байтс"]
    assert to_jsonable(datetime(2026, 9, 30, 9, 0)) == "2026-09-30T09:00:00"


def test_encoded_batch_is_script_safe() -> None:
    encoded = encode_batch([event_message(SpeakRequested("</script><b>"))])
    assert "</script>" not in encoded
    assert json.loads(encoded)[0]["data"]["text"] == "</script><b>"


def test_api_publishes_text_command() -> None:
    bus = RecordingBus()
    api = JarvisApi(bus, FakeDialogs(None))
    assert api.send_command("  відкрий хром ")["ok"]
    assert api.send_command("   ")["ok"] is False
    assert bus.published == [CommandReceived("відкрий хром", CommandSource.TEXT)]


def test_api_validates_binding_actions() -> None:
    bus = RecordingBus()
    api = JarvisApi(bus, FakeDialogs(None))
    macro = {"type": "macro", "steps": [{"type": "open_app", "target": "Discord"}, {"type": "launch", "target": "steam://rungameid/570"}]}
    assert api.save_binding(None, "бойовий режим", macro)["ok"]
    assert api.save_binding(None, "x", {"type": "teleport"})["ok"] is False
    assert api.save_binding(None, " ", macro)["ok"] is False
    saved = bus.published[0]
    assert isinstance(saved, BindingSaveRequested)
    assert saved.action.type is ActionType.MACRO
    assert [step.target for step in saved.action.steps] == ["Discord", "steam://rungameid/570"]


def test_api_word_and_dialog_driven_calls(tmp_path: Path) -> None:
    exe = tmp_path / "game.exe"
    bus = RecordingBus()
    api = JarvisApi(bus, FakeDialogs(exe))
    api.add_word("Malwarebytes", {"type": "open_app", "target": "Malwarebytes"})
    api.add_program("моя гра")
    api.locate_program("фотошоп")
    added, program, located = bus.published
    assert isinstance(added, VocabularyWordAddRequested)
    assert added.action is not None and added.action.target == "Malwarebytes"
    assert program == ProgramAddRequested("моя гра", exe, ("моя гра",))
    assert located == ProgramLocationProvided("фотошоп", exe)


def test_api_cancelled_dialog_publishes_nothing() -> None:
    bus = RecordingBus()
    api = JarvisApi(bus, FakeDialogs(None))
    assert api.import_bindings() == {"ok": True, "cancelled": True}
    assert api.add_program("x") == {"ok": True, "cancelled": True}
    assert bus.published == []


def test_region_fraction_roundtrip() -> None:
    bus = RecordingBus()
    api = JarvisApi(bus, FakeDialogs(None))
    api.region_selected("r1", [0.25, 0.5, 0.75, 1.0])
    api.region_selected("r2", None)
    assert bus.published == [RegionSelected("r1", (0.25, 0.5, 0.75, 1.0)), RegionSelected("r2", None)]
    assert fraction_to_box((0.25, 0.5, 0.75, 1.0), 1920, 1080) == (480, 540, 1440, 1080)


def test_relay_waits_for_window_and_compacts_levels() -> None:
    bus = EventBus()
    ready = threading.Event()
    delivered: list[list[dict]] = []
    got_batch = threading.Event()

    def sink(payload: str) -> None:
        delivered.append(json.loads(payload))
        got_batch.set()

    relay = EventRelay(bus, (MicLevelChanged, SpeakRequested), sink, ready, "test")
    relay.start()
    for level in (0.1, 0.5, 0.9):
        bus.dispatch_now(MicLevelChanged(level))
    bus.dispatch_now(SpeakRequested("Слухаю, сер."))
    assert not got_batch.wait(0.2)
    ready.set()
    assert got_batch.wait(2)
    relay.stop()
    batch = delivered[0]
    levels = [message for message in batch if message["type"] == "MicLevelChanged"]
    assert len(levels) == 1
    assert levels[0]["data"]["level"] == 0.9
    assert any(message["data"].get("text") == "Слухаю, сер." for message in batch)


@pytest.mark.parametrize("page", ["index", "hud", "region"])
def test_web_pages_inline_all_assets(page: str) -> None:
    html = WebAssets().page(page, {"__REQUEST_ID__": "abc", "__IMAGE_DATA__": "data:,"})
    assert '<link rel="stylesheet"' not in html
    assert "<script src=" not in html
    assert "window.jarvis" in html
    assert "__REQUEST_ID__" not in html
