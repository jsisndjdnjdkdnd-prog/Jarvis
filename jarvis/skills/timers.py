from __future__ import annotations

import itertools
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from jarvis.core.context import DialogContext, SkillResult
from jarvis.core.errors import AudioDeviceError
from jarvis.core.event_bus import EventBus
from jarvis.core.events import NotificationRequested, SpeakRequested, TimerFinished
from jarvis.core.intent import Intent, IntentName
from jarvis.core.scheduler import Scheduler
from jarvis.skills.formatting import format_duration, format_duration_accusative
from jarvis.speech.audio_io import AudioPlayer

logger = logging.getLogger(__name__)

MAX_TIMER_SECONDS = 24 * 3600


@dataclass(frozen=True)
class ActiveTimer:
    timer_id: str
    label: str
    duration_seconds: int
    ends_at: float

    def remaining(self, now: float) -> int:
        return max(0, int(round(self.ends_at - now)))


class TimerService:
    def __init__(
        self,
        scheduler: Scheduler,
        bus: EventBus,
        player: AudioPlayer,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._scheduler = scheduler
        self._bus = bus
        self._player = player
        self._clock = clock
        self._timers: dict[str, ActiveTimer] = {}
        self._lock = threading.Lock()
        self._ids = itertools.count(1)

    def start(self, seconds: int) -> ActiveTimer:
        timer_id = f"timer-{next(self._ids)}"
        timer = ActiveTimer(
            timer_id=timer_id,
            label=format_duration_accusative(seconds),
            duration_seconds=seconds,
            ends_at=self._clock() + seconds,
        )
        with self._lock:
            self._timers[timer_id] = timer
        self._scheduler.schedule_in(timer_id, seconds, lambda: self._finish(timer_id))
        return timer

    def active(self) -> list[ActiveTimer]:
        with self._lock:
            return sorted(self._timers.values(), key=lambda timer: timer.ends_at)

    def remaining(self, timer: ActiveTimer) -> int:
        return timer.remaining(self._clock())

    def cancel(self, timer_id: str) -> bool:
        with self._lock:
            removed = self._timers.pop(timer_id, None)
        if removed is None:
            return False
        self._scheduler.cancel(timer_id)
        return True

    def _finish(self, timer_id: str) -> None:
        with self._lock:
            timer = self._timers.pop(timer_id, None)
        if timer is None:
            return
        self._bus.publish(TimerFinished(timer.label))
        self._bus.publish(NotificationRequested("Таймер", f"Таймер на {timer.label} завершено"))
        try:
            self._player.beep()
        except AudioDeviceError as error:
            logger.warning("Не вдалося відтворити сигнал: %s", error)
        self._bus.publish(SpeakRequested(f"Сер, таймер на {timer.label} завершено."))


class TimersSkill:
    name = "timers"
    intents = frozenset({IntentName.TIMER_SET, IntentName.TIMER_STATUS, IntentName.TIMER_CANCEL})

    def __init__(self, timers: TimerService) -> None:
        self._timers = timers

    def handle(self, intent: Intent, context: DialogContext) -> SkillResult:
        if intent.name is IntentName.TIMER_SET:
            return self._set(intent)
        if intent.name is IntentName.TIMER_STATUS:
            return self._status()
        return self._cancel(intent)

    def _set(self, intent: Intent) -> SkillResult:
        seconds = intent.duration_seconds or 0
        if seconds <= 0:
            return SkillResult("На скільки поставити таймер, сер?", success=False)
        if seconds > MAX_TIMER_SECONDS:
            return SkillResult("Таймер може бути не довшим за добу. Для цього краще нагадування.", success=False)
        timer = self._timers.start(seconds)
        return SkillResult(f"Таймер на {timer.label} запущено.", learnable=False)

    def _status(self) -> SkillResult:
        timers = self._timers.active()
        if not timers:
            return SkillResult("Активних таймерів немає, сер.")
        parts = [
            f"{index}-й: лишилось {format_duration(self._timers.remaining(timer))}"
            for index, timer in enumerate(timers, start=1)
        ]
        if len(parts) == 1:
            return SkillResult(f"Лишилось {format_duration(self._timers.remaining(timers[0]))}.")
        return SkillResult("; ".join(parts) + ".")

    def _cancel(self, intent: Intent) -> SkillResult:
        timers = self._timers.active()
        if not timers:
            return SkillResult("Скасовувати нічого, таймерів немає.")
        targets = timers if intent.mode == "all" or len(timers) == 1 else timers[:1]
        for timer in targets:
            self._timers.cancel(timer.timer_id)
        if len(targets) == 1:
            return SkillResult(f"Таймер на {targets[0].label} скасовано.")
        return SkillResult(f"Скасовано таймерів: {len(targets)}.")
