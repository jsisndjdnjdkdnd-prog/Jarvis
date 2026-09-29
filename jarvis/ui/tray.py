from __future__ import annotations

import logging
import threading
from typing import Any

from PIL import Image, ImageDraw

from jarvis.core.event_bus import EventBus
from jarvis.core.events import HudToggleRequested, ListenRequested, ShowWindowRequested, ShutdownRequested

logger = logging.getLogger(__name__)

ICON_SIZE = 64
ACCENT = "#00e5ff"


def create_icon_image(size: int = ICON_SIZE) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    margin = size // 10
    draw.ellipse((margin, margin, size - margin, size - margin), outline=ACCENT, width=size // 12)
    inner = size // 3
    draw.ellipse((inner, inner, size - inner, size - inner), fill=ACCENT)
    return image


class TrayIcon:
    def __init__(self, bus: EventBus, title: str) -> None:
        self._bus = bus
        self._title = title
        self._icon: Any = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        try:
            import pystray
        except ImportError:
            logger.warning("pystray не встановлено — трей вимкнено")
            return
        menu = pystray.Menu(
            pystray.MenuItem("Показати", lambda: self._bus.publish(ShowWindowRequested()), default=True),
            pystray.MenuItem("Слухати", lambda: self._bus.publish(ListenRequested())),
            pystray.MenuItem("HUD увімк/вимк", lambda: self._bus.publish(HudToggleRequested())),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Вихід", lambda: self._bus.publish(ShutdownRequested())),
        )
        self._icon = pystray.Icon("jarvis", create_icon_image(), self._title, menu)
        self._thread = threading.Thread(target=self._icon.run, name="tray", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._icon is not None:
            self._icon.stop()
