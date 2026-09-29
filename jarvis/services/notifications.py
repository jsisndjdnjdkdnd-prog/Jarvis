from __future__ import annotations

import logging
from pathlib import Path

from jarvis.core.event_bus import EventBus
from jarvis.core.events import NotificationRequested
from jarvis.skills.platform import is_windows

logger = logging.getLogger(__name__)

APP_ID = "J.A.R.V.I.S."


class ToastNotifier:
    def __init__(self, bus: EventBus, icon: Path | None = None) -> None:
        self._bus = bus
        self._icon = icon

    def start(self) -> None:
        self._bus.subscribe(NotificationRequested, self._show)

    def _show(self, event: NotificationRequested) -> None:
        if not is_windows():
            logger.info("Сповіщення: %s — %s", event.title, event.message)
            return
        try:
            from winotify import Notification, audio
        except ImportError:
            logger.warning("winotify не встановлено — сповіщення вимкнені")
            return
        toast = Notification(
            app_id=APP_ID,
            title=event.title,
            msg=event.message,
            icon=str(self._icon) if self._icon and self._icon.exists() else "",
        )
        toast.set_audio(audio.Reminder, loop=False)
        try:
            toast.show()
        except OSError as error:
            logger.warning("Toast-сповіщення не показано: %s", error)
