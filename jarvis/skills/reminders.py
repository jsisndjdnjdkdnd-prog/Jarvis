from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta

from rapidfuzz import fuzz

from jarvis.core.config import RemindersSection
from jarvis.core.context import DialogContext, SkillResult
from jarvis.core.errors import StorageError
from jarvis.core.event_bus import EventBus
from jarvis.core.events import NotificationRequested, ReminderDue, RemindersChanged, SpeakRequested
from jarvis.core.intent import Intent, IntentName
from jarvis.core.models import Reminder, ReminderStatus
from jarvis.core.scheduler import Scheduler
from jarvis.skills.formatting import format_moment
from jarvis.storage.repositories.reminders import ReminderRepository

logger = logging.getLogger(__name__)

REMINDER_JOB_ID = "reminders-check"
CANCEL_MATCH_THRESHOLD = 60.0
MISSED_GRACE = timedelta(hours=12)


class ReminderService:
    def __init__(
        self,
        repository: ReminderRepository,
        scheduler: Scheduler,
        bus: EventBus,
        settings: RemindersSection,
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._repository = repository
        self._scheduler = scheduler
        self._bus = bus
        self._settings = settings
        self._clock = clock

    def start(self) -> None:
        self._scheduler.schedule_every(REMINDER_JOB_ID, self._settings.check_interval_seconds, self.check_due)
        self.check_due()

    def add(self, message: str, when: datetime) -> Reminder:
        reminder = self._repository.add(message, when)
        self._bus.publish(RemindersChanged())
        return reminder

    def pending(self) -> list[Reminder]:
        return self._repository.pending()

    def cancel(self, reminder_id: int) -> bool:
        cancelled = self._repository.set_status(reminder_id, ReminderStatus.CANCELLED)
        if cancelled:
            self._bus.publish(RemindersChanged())
        return cancelled

    def check_due(self) -> None:
        now = self._clock()
        try:
            due = self._repository.due(now)
        except StorageError:
            logger.exception("Не вдалося перевірити нагадування")
            return
        for reminder in due:
            self._fire(reminder, now)
        if due:
            self._bus.publish(RemindersChanged())

    def _fire(self, reminder: Reminder, now: datetime) -> None:
        if reminder.id is None:
            return
        self._repository.set_status(reminder.id, ReminderStatus.DONE)
        late = now - reminder.due_at > MISSED_GRACE
        prefix = "Пропущене нагадування" if late else "Нагадування"
        self._bus.publish(ReminderDue(reminder))
        self._bus.publish(NotificationRequested(prefix, reminder.message))
        self._bus.publish(SpeakRequested(f"Сер, {prefix.lower()}: {reminder.message}."))


class RemindersSkill:
    name = "reminders"
    intents = frozenset({IntentName.REMINDER_ADD, IntentName.REMINDER_LIST, IntentName.REMINDER_CANCEL})

    def __init__(self, reminders: ReminderService, clock: Callable[[], datetime] = datetime.now) -> None:
        self._reminders = reminders
        self._clock = clock

    def handle(self, intent: Intent, context: DialogContext) -> SkillResult:
        if intent.name is IntentName.REMINDER_ADD:
            return self._add(intent)
        if intent.name is IntentName.REMINDER_LIST:
            return self._list()
        return self._cancel(intent)

    def _add(self, intent: Intent) -> SkillResult:
        if intent.when is None:
            return SkillResult("Коли нагадати, сер? Скажіть, наприклад: нагадай завтра о дев'ятій.", success=False)
        now = self._clock()
        when = intent.when.replace(tzinfo=None)
        if when <= now:
            return SkillResult("Цей час уже минув, сер.", success=False)
        message = (intent.message or "").strip() or "без опису"
        self._reminders.add(message, when)
        return SkillResult(f"Нагадаю {format_moment(when, now)}: {message}.", learnable=False)

    def _list(self) -> SkillResult:
        pending = self._reminders.pending()
        if not pending:
            return SkillResult("Нагадувань немає, сер.")
        now = self._clock()
        items = "; ".join(f"{format_moment(item.due_at, now)} — {item.message}" for item in pending[:5])
        suffix = f" І ще {len(pending) - 5}." if len(pending) > 5 else ""
        return SkillResult(f"У вас {len(pending)}: {items}.{suffix}")

    def _cancel(self, intent: Intent) -> SkillResult:
        pending = self._reminders.pending()
        if not pending:
            return SkillResult("Скасовувати нічого, сер.")
        if intent.mode == "all":
            for reminder in pending:
                if reminder.id is not None:
                    self._reminders.cancel(reminder.id)
            return SkillResult(f"Скасовано нагадувань: {len(pending)}.")
        target = self._match(pending, intent.query or "")
        if target is None or target.id is None:
            return SkillResult("Не знайшов такого нагадування, сер.", success=False)
        self._reminders.cancel(target.id)
        return SkillResult(f"Нагадування «{target.message}» скасовано.")

    @staticmethod
    def _match(reminders: list[Reminder], query: str) -> Reminder | None:
        if not query:
            return reminders[0]
        scored = [(fuzz.token_set_ratio(query, item.message), item) for item in reminders]
        score, best = max(scored, key=lambda pair: pair[0])
        return best if score >= CANCEL_MATCH_THRESHOLD else None
