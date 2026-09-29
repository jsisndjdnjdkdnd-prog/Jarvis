from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

from jarvis.core.intent import Intent
from jarvis.core.models import Program, Track, VocabularyAlias

CONFIRMATION_TTL_SECONDS = 45.0
HISTORY_SIZE = 10


@dataclass(frozen=True)
class SkillResult:
    reply: str
    success: bool = True
    confirmation: PendingConfirmation | None = None
    learnable: bool = True
    end_conversation: bool = False
    speak: bool = True


@dataclass(frozen=True)
class PendingConfirmation:
    prompt: str
    on_confirm: Callable[[], SkillResult]
    on_deny_reply: str = "Скасовано, сер."
    created_at: float = field(default_factory=time.monotonic)

    def is_expired(self, now: float) -> bool:
        return now - self.created_at > CONFIRMATION_TTL_SECONDS


@dataclass(frozen=True)
class ExchangeRecord:
    text: str
    intent: Intent | None
    reply: str
    success: bool


class DialogContext:
    def __init__(self, conversation_mode: bool = True, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self.conversation_mode = conversation_mode
        self._lock = threading.RLock()
        self._last_program: Program | None = None
        self._last_track: Track | None = None
        self._pending: PendingConfirmation | None = None
        self._last_aliases: tuple[VocabularyAlias, ...] = ()
        self._history: deque[ExchangeRecord] = deque(maxlen=HISTORY_SIZE)

    @property
    def last_program(self) -> Program | None:
        with self._lock:
            return self._last_program

    def remember_program(self, program: Program) -> None:
        with self._lock:
            self._last_program = program

    def forget_program(self, program: Program) -> None:
        with self._lock:
            if self._last_program is not None and self._last_program.name == program.name:
                self._last_program = None

    @property
    def last_track(self) -> Track | None:
        with self._lock:
            return self._last_track

    def remember_track(self, track: Track | None) -> None:
        with self._lock:
            self._last_track = track

    def set_pending_confirmation(self, confirmation: PendingConfirmation) -> None:
        with self._lock:
            self._pending = confirmation

    def take_pending_confirmation(self) -> PendingConfirmation | None:
        with self._lock:
            pending = self._pending
            self._pending = None
        if pending is None or pending.is_expired(self._clock()):
            return None
        return pending

    def has_pending_confirmation(self) -> bool:
        with self._lock:
            if self._pending is None:
                return False
            if self._pending.is_expired(self._clock()):
                self._pending = None
                return False
            return True

    def remember_aliases(self, aliases: tuple[VocabularyAlias, ...]) -> None:
        with self._lock:
            self._last_aliases = aliases

    def take_last_aliases(self) -> tuple[VocabularyAlias, ...]:
        with self._lock:
            aliases = self._last_aliases
            self._last_aliases = ()
            return aliases

    def record_exchange(self, record: ExchangeRecord) -> None:
        with self._lock:
            self._history.append(record)

    def recent_exchanges(self) -> tuple[ExchangeRecord, ...]:
        with self._lock:
            return tuple(self._history)
