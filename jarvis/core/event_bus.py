from __future__ import annotations

import logging
import queue
import threading
from collections import defaultdict
from collections.abc import Callable
from typing import TypeVar, cast

from jarvis.core.events import Event

logger = logging.getLogger(__name__)

E = TypeVar("E", bound=Event)
Handler = Callable[[E], None]
Unsubscribe = Callable[[], None]

_STOP = object()


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[type[Event], list[Callable[[Event], None]]] = defaultdict(list)
        self._lock = threading.RLock()
        self._queue: queue.Queue[object] = queue.Queue()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="event-bus", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._thread is None:
            return
        self._queue.put(_STOP)
        self._thread.join(timeout=2)
        self._thread = None

    def subscribe(self, event_type: type[E], handler: Handler[E]) -> Unsubscribe:
        registered = cast(Callable[[Event], None], handler)
        with self._lock:
            self._handlers[event_type].append(registered)

        def unsubscribe() -> None:
            with self._lock:
                handlers = self._handlers.get(event_type, [])
                if registered in handlers:
                    handlers.remove(registered)

        return unsubscribe

    def publish(self, event: Event) -> None:
        self._queue.put(event)

    def dispatch_now(self, event: Event) -> None:
        self._dispatch(event)

    def wait_for(
        self,
        event_type: type[E],
        predicate: Callable[[E], bool],
        timeout: float,
        trigger: Event | None = None,
    ) -> E | None:
        received: list[E] = []
        done = threading.Event()

        def handler(event: E) -> None:
            if done.is_set() or not predicate(event):
                return
            received.append(event)
            done.set()

        unsubscribe = self.subscribe(event_type, handler)
        try:
            if trigger is not None:
                self.publish(trigger)
            done.wait(timeout)
        finally:
            unsubscribe()
        return received[0] if received else None

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is _STOP:
                return
            if isinstance(item, Event):
                self._dispatch(item)

    def _dispatch(self, event: Event) -> None:
        for handler in self._handlers_for(type(event)):
            self._invoke(handler, event)

    def _handlers_for(self, event_type: type[Event]) -> list[Callable[[Event], None]]:
        with self._lock:
            collected: list[Callable[[Event], None]] = []
            for registered_type, handlers in self._handlers.items():
                if issubclass(event_type, registered_type):
                    collected.extend(handlers)
            return collected

    @staticmethod
    def _invoke(handler: Callable[[Event], None], event: Event) -> None:
        try:
            handler(event)
        except Exception:
            logger.exception("Обробник %r впав на події %s", handler, type(event).__name__)
