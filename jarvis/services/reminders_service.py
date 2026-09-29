from __future__ import annotations

from jarvis.core.event_bus import EventBus
from jarvis.core.events import ReminderCancelRequested, RemindersChanged, RemindersListed, RemindersListRequested
from jarvis.skills.reminders import ReminderService


class RemindersUiService:
    def __init__(self, bus: EventBus, reminders: ReminderService) -> None:
        self._bus = bus
        self._reminders = reminders

    def start(self) -> None:
        self._bus.subscribe(RemindersListRequested, lambda _: self._publish())
        self._bus.subscribe(RemindersChanged, lambda _: self._publish())
        self._bus.subscribe(ReminderCancelRequested, lambda event: self._reminders.cancel(event.reminder_id))

    def _publish(self) -> None:
        self._bus.publish(RemindersListed(tuple(self._reminders.pending())))
