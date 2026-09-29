from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

import webview

from jarvis.core.config import UiSection
from jarvis.ui.js_api import JarvisApi
from jarvis.ui.web_assets import WebAssets

logger = logging.getLogger(__name__)

BACKGROUND = "#04070c"
MIN_SIZE = (1080, 680)
RECEIVE_SCRIPT = "window.jarvis && window.jarvis.receive({payload});"


class WebviewDialogs:
    def open_file(self, file_types: tuple[str, ...]) -> Path | None:
        return self._first(self._show(webview.FileDialog.OPEN, file_types=file_types))

    def save_file(self, default_name: str, file_types: tuple[str, ...]) -> Path | None:
        return self._first(self._show(webview.FileDialog.SAVE, save_filename=default_name, file_types=file_types))

    def choose_folder(self) -> Path | None:
        return self._first(self._show(webview.FileDialog.FOLDER))

    @staticmethod
    def _show(dialog_type: webview.FileDialog, **options: Any) -> Any:
        window = webview.active_window() or (webview.windows[0] if webview.windows else None)
        if window is None:
            return None
        return window.create_file_dialog(dialog_type, **options)

    @staticmethod
    def _first(result: Any) -> Path | None:
        if not result:
            return None
        if isinstance(result, str):
            return Path(result)
        return Path(result[0])


class MainWindow:
    def __init__(self, assets: WebAssets, api: JarvisApi, settings: UiSection, title: str) -> None:
        self._settings = settings
        self._allow_close = not settings.tray_enabled
        self.ready = threading.Event()
        self._window = webview.create_window(
            title,
            html=assets.page("index"),
            js_api=api,
            width=settings.window_width,
            height=settings.window_height,
            min_size=MIN_SIZE,
            background_color=BACKGROUND,
            hidden=settings.start_minimized and settings.tray_enabled,
            text_select=True,
        )
        self._window.events.loaded += self.ready.set
        self._window.events.closing += self._on_closing

    @property
    def native(self) -> webview.Window:
        return self._window

    def push(self, payload: str) -> None:
        self._window.run_js(RECEIVE_SCRIPT.format(payload=payload))

    def show(self) -> None:
        self._window.show()
        self._window.restore()

    def hide(self) -> None:
        self._window.hide()

    def quit(self) -> None:
        self._allow_close = True
        self._window.destroy()

    def _on_closing(self) -> bool:
        if self._allow_close:
            return True
        logger.info("Головне вікно сховано у трей")
        threading.Thread(target=self._window.hide, daemon=True).start()
        return False
