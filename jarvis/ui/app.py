from __future__ import annotations

import logging
import threading
from pathlib import Path

import webview

from jarvis.core.config import AppConfig
from jarvis.core.event_bus import EventBus
from jarvis.core.events import HideWindowRequested, HudToggleRequested, ShowWindowRequested, ShutdownRequested
from jarvis.skills.platform import is_windows
from jarvis.ui.event_relay import MAIN_WINDOW_EVENTS, EventRelay
from jarvis.ui.hotkeys import PushToTalkHotkey
from jarvis.ui.hud import HudWindow
from jarvis.ui.js_api import JarvisApi
from jarvis.ui.main_window import MainWindow, WebviewDialogs
from jarvis.ui.region_selector import RegionSelectorWindows
from jarvis.ui.tray import TrayIcon
from jarvis.ui.web_assets import WebAssets

logger = logging.getLogger(__name__)


class DesktopUi:
    def __init__(self, bus: EventBus, config: AppConfig, storage_dir: Path) -> None:
        self._bus = bus
        self._config = config
        self._storage_dir = storage_dir
        self._assets = WebAssets()
        self._api = JarvisApi(bus, WebviewDialogs())
        self._hud = HudWindow(bus, self._assets, self._api, config.ui.hud_size)
        self._regions = RegionSelectorWindows(bus, self._assets, self._api)
        self._tray = TrayIcon(bus, config.app.name)
        self._hotkey = PushToTalkHotkey(bus, config.ui.push_to_talk_hotkey)
        self._main: MainWindow | None = None
        self._relay: EventRelay | None = None
        self._stopped = threading.Event()

    def run(self) -> None:
        self._main = MainWindow(self._assets, self._api, self._config.ui, self._config.app.name)
        self._relay = EventRelay(self._bus, MAIN_WINDOW_EVENTS, self._main.push, self._main.ready, "main")
        self._relay.start()
        self._regions.start()
        self._bus.subscribe(ShowWindowRequested, lambda _: self._main.show() if self._main else None)
        self._bus.subscribe(HideWindowRequested, lambda _: self._main.hide() if self._main else None)
        self._bus.subscribe(HudToggleRequested, lambda _: self._hud.toggle())
        self._bus.subscribe(ShutdownRequested, lambda _: self._shutdown())
        if self._config.ui.tray_enabled:
            self._tray.start()
        self._hotkey.start()
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        webview.start(
            func=self._on_started,
            gui="edgechromium" if is_windows() else None,
            debug=self._config.ui.devtools,
            private_mode=False,
            storage_path=str(self._storage_dir),
        )
        self._stop_services()

    def _on_started(self) -> None:
        if self._config.ui.hud_enabled:
            self._hud.open()

    def _shutdown(self) -> None:
        if self._stopped.is_set():
            return
        self._stop_services()
        main = self._main.native if self._main is not None else None
        for window in list(webview.windows):
            if window is not main:
                window.destroy()
        if self._main is not None:
            self._main.quit()

    def _stop_services(self) -> None:
        if self._stopped.is_set():
            return
        self._stopped.set()
        logger.info("Завершення роботи інтерфейсу")
        self._hotkey.stop()
        self._tray.stop()
        self._hud.close()
        if self._relay is not None:
            self._relay.stop()
