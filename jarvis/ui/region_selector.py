from __future__ import annotations

import base64
import logging
import threading

import webview

from jarvis.core.event_bus import EventBus
from jarvis.core.events import RegionSelected, RegionSelectionRequested
from jarvis.ui.js_api import JarvisApi
from jarvis.ui.web_assets import WebAssets

logger = logging.getLogger(__name__)


class RegionSelectorWindows:
    def __init__(self, bus: EventBus, assets: WebAssets, api: JarvisApi) -> None:
        self._bus = bus
        self._assets = assets
        self._api = api
        self._windows: dict[str, webview.Window] = {}
        self._lock = threading.Lock()

    def start(self) -> None:
        self._bus.subscribe(RegionSelectionRequested, self._open)
        self._bus.subscribe(RegionSelected, self._close)

    def _open(self, event: RegionSelectionRequested) -> None:
        try:
            encoded = base64.b64encode(event.preview_path.read_bytes()).decode("ascii")
        except OSError as error:
            logger.error("Не вдалося прочитати прев'ю скріншота: %s", error)
            self._bus.publish(RegionSelected(event.request_id, None))
            return
        html = self._assets.page(
            "region",
            {"__IMAGE_DATA__": f"data:image/jpeg;base64,{encoded}", "__REQUEST_ID__": event.request_id},
        )
        window = webview.create_window(
            "Виділення області",
            html=html,
            js_api=self._api,
            fullscreen=True,
            frameless=True,
            on_top=True,
            easy_drag=False,
            background_color="#000000",
        )
        with self._lock:
            self._windows[event.request_id] = window

    def _close(self, event: RegionSelected) -> None:
        with self._lock:
            window = self._windows.pop(event.request_id, None)
        if window is not None:
            window.destroy()
