from __future__ import annotations

import logging
from typing import Any

from jarvis.core.event_bus import EventBus
from jarvis.core.events import ListenRequested

logger = logging.getLogger(__name__)


class PushToTalkHotkey:
    def __init__(self, bus: EventBus, combination: str) -> None:
        self._bus = bus
        self._combination = combination
        self._handle: Any = None

    def start(self) -> None:
        if not self._combination:
            return
        try:
            import keyboard
        except ImportError:
            logger.warning("Бібліотека keyboard недоступна — push-to-talk вимкнено")
            return
        try:
            self._handle = keyboard.add_hotkey(self._combination, self._trigger)
        except (ValueError, OSError) as error:
            logger.warning("Не вдалося зареєструвати гарячу клавішу %s: %s", self._combination, error)
            return
        logger.info("Push-to-talk: %s", self._combination)

    def stop(self) -> None:
        if self._handle is None:
            return
        import keyboard

        try:
            keyboard.remove_hotkey(self._handle)
        except (KeyError, ValueError):
            return

    def _trigger(self) -> None:
        self._bus.publish(ListenRequested())
