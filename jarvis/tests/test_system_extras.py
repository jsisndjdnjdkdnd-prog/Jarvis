from __future__ import annotations

import pytest

from jarvis.core.context import DialogContext, SkillResult
from jarvis.core.event_bus import EventBus
from jarvis.core.events import ListeningModeChanged
from jarvis.core.intent import Intent, IntentName
from jarvis.skills.system_extras import SystemExtrasSkill, WindowsPowerExtras


class FakeVolume:
    def __init__(self, level: int) -> None:
        self._level = level

    def get(self) -> int:
        return self._level

    def set(self, percent: int) -> None:
        self._level = percent

    def set_muted(self, muted: bool) -> None:
        return None


class FakePower:
    def __init__(self) -> None:
        self.slept = False
        self.emptied = False

    def sleep(self) -> None:
        self.slept = True

    def empty_recycle_bin(self) -> None:
        self.emptied = True


class FakeOpener:
    def __init__(self) -> None:
        self.opened: list[str] = []

    def open(self, target: str) -> None:
        self.opened.append(target)


class RecordingBus(EventBus):
    def __init__(self) -> None:
        super().__init__()
        self.modes: list[bool] = []

    def publish(self, event) -> None:
        if isinstance(event, ListeningModeChanged):
            self.modes.append(event.always_listen)


def build() -> tuple[SystemExtrasSkill, RecordingBus, FakePower, FakeOpener, list]:
    bus = RecordingBus()
    modes = bus.modes
    power = FakePower()
    opener = FakeOpener()
    skill = SystemExtrasSkill(bus, FakeVolume(42), power, opener)
    return skill, bus, power, opener, modes


def handle(skill: SystemExtrasSkill, intent: Intent) -> SkillResult:
    return skill.handle(intent, DialogContext())


def test_volume_get() -> None:
    skill, *_ = build()
    result = handle(skill, Intent(name=IntentName.VOLUME_GET))
    assert "42" in result.reply


def test_sleep() -> None:
    skill, _, power, _, _ = build()
    result = handle(skill, Intent(name=IntentName.SLEEP_PC))
    assert power.slept
    assert result.success


def test_empty_recycle_bin_requires_confirmation() -> None:
    skill, _, power, _, _ = build()
    result = handle(skill, Intent(name=IntentName.EMPTY_RECYCLE_BIN))
    assert result.confirmation is not None
    assert not power.emptied
    confirmed = result.confirmation.on_confirm()
    assert power.emptied
    assert "очищено" in confirmed.reply.lower()


@pytest.mark.parametrize(
    ("page", "uri"),
    [
        ("bluetooth", "ms-settings:bluetooth"),
        ("sound", "ms-settings:sound"),
        ("wifi", "ms-settings:network-wifi"),
    ],
)
def test_open_settings_uri(page: str, uri: str) -> None:
    skill, _, _, opener, _ = build()
    handle(skill, Intent(name=IntentName.OPEN_SETTINGS, target=page))
    assert opener.opened == [uri]


def test_open_settings_unknown_page_opens_root() -> None:
    skill, _, _, opener, _ = build()
    handle(skill, Intent(name=IntentName.OPEN_SETTINGS, target="unknown"))
    assert opener.opened == ["ms-settings:"]


def test_listen_mode_publishes_event() -> None:
    skill, _, _, _, modes = build()
    handle(skill, Intent(name=IntentName.LISTEN_MODE, mode="always"))
    handle(skill, Intent(name=IntentName.LISTEN_MODE, mode="wake"))
    assert modes == [True, False]


def test_power_extras_is_constructible() -> None:
    assert isinstance(WindowsPowerExtras(), WindowsPowerExtras)
