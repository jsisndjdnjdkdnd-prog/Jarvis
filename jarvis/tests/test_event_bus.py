from __future__ import annotations

import threading
from pathlib import Path

from jarvis.core.event_bus import EventBus
from jarvis.core.events import Event, RegionSelected, RegionSelectionRequested, SpeakRequested


def test_publish_is_delivered_asynchronously() -> None:
    bus = EventBus()
    received: list[str] = []
    done = threading.Event()

    def handler(event: SpeakRequested) -> None:
        received.append(event.text)
        done.set()

    bus.subscribe(SpeakRequested, handler)
    bus.start()
    bus.publish(SpeakRequested("Слухаю, сер."))
    assert done.wait(2)
    bus.stop()
    assert received == ["Слухаю, сер."]


def test_failing_handler_does_not_break_others() -> None:
    bus = EventBus()
    received: list[Event] = []

    def broken(event: SpeakRequested) -> None:
        raise RuntimeError("boom")

    bus.subscribe(SpeakRequested, broken)
    bus.subscribe(SpeakRequested, received.append)
    bus.dispatch_now(SpeakRequested("ok"))
    assert len(received) == 1


def test_unsubscribe() -> None:
    bus = EventBus()
    received: list[Event] = []
    unsubscribe = bus.subscribe(SpeakRequested, received.append)
    unsubscribe()
    bus.dispatch_now(SpeakRequested("ok"))
    assert received == []


def test_wait_for_request_response() -> None:
    bus = EventBus()
    bus.subscribe(
        RegionSelectionRequested,
        lambda event: bus.publish(RegionSelected(event.request_id, (0.1, 0.2, 0.5, 0.6))),
    )
    bus.start()
    response = bus.wait_for(
        RegionSelected,
        lambda event: event.request_id == "abc",
        timeout=2,
        trigger=RegionSelectionRequested("abc", Path("preview.jpg")),
    )
    bus.stop()
    assert response is not None
    assert response.fraction == (0.1, 0.2, 0.5, 0.6)
