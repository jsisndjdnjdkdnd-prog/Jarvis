from __future__ import annotations

import logging
import threading

import webview

from jarvis.core.event_bus import EventBus
from jarvis.ui.event_relay import HUD_EVENTS, EventRelay
from jarvis.ui.js_api import JarvisApi
from jarvis.ui.main_window import RECEIVE_SCRIPT
from jarvis.ui.web_assets import WebAssets

logger = logging.getLogger(__name__)

MARGIN_RIGHT = 28
MARGIN_BOTTOM = 76


class HudWindow:
    def __init__(self, bus: EventBus, assets: WebAssets, api: JarvisApi, size: int) -> None:
        self._bus = bus
        self._assets = assets
        self._api = api
        self._size = size
        self._window: webview.Window | None = None
        self._relay: EventRelay | None = None
        self._visible = False
        self._lock = threading.Lock()

    def open(self) -> None:
        with self._lock:
            if self._window is not None:
                return
            x, y = self._corner()
            ready = threading.Event()
            self._window = webview.create_window(
                "J.A.R.V.I.S. HUD",
                html=self._assets.page("hud"),
                js_api=self._api,
                width=self._size,
                height=self._size + 34,
                x=x,
                y=y,
                resizable=False,
                frameless=True,
                easy_drag=True,
                on_top=True,
                transparent=True,
                shadow=False,
                focus=False,
                background_color="#000000",
            )
            self._window.events.loaded += ready.set
            self._relay = EventRelay(self._bus, HUD_EVENTS, self._push, ready, "hud")
            self._relay.start()
            self._visible = True

    def toggle(self) -> None:
        if self._window is None:
            self.open()
            return
        if self._visible:
            self._window.hide()
        else:
            self._window.show()
        self._visible = not self._visible

    def close(self) -> None:
        if self._relay is not None:
            self._relay.stop()

    def _push(self, payload: str) -> None:
        if self._window is not None:
            self._window.run_js(RECEIVE_SCRIPT.format(payload=payload))

    def _corner(self) -> tuple[int, int]:
        screens = webview.screens
        if not screens:
            return 40, 40
        screen = screens[0]
        return (
            screen.x + screen.width - self._size - MARGIN_RIGHT,
            screen.y + screen.height - self._size - 34 - MARGIN_BOTTOM,
        )
