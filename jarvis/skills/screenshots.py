from __future__ import annotations

import io
import logging
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from jarvis.core.config import ScreenshotsSection
from jarvis.core.context import DialogContext, SkillResult
from jarvis.core.errors import ActionExecutionError, SkillError
from jarvis.core.event_bus import EventBus
from jarvis.core.events import RegionSelected, RegionSelectionRequested
from jarvis.core.intent import Intent, IntentName, ScreenshotMode
from jarvis.skills.platform import is_windows

logger = logging.getLogger(__name__)

BoundingBox = tuple[int, int, int, int]
Fraction = tuple[float, float, float, float]
PREVIEW_MAX_WIDTH = 1920
PREVIEW_QUALITY = 72
PRIMARY_MONITOR = 1
ALL_MONITORS = 0


def fraction_to_box(fraction: Fraction, width: int, height: int) -> BoundingBox:
    left, top, right, bottom = (max(0.0, min(1.0, value)) for value in fraction)
    box = (int(left * width), int(top * height), int(round(right * width)), int(round(bottom * height)))
    if box[2] - box[0] < 2 or box[3] - box[1] < 2:
        raise ActionExecutionError("Надто мала область для скріншота")
    return box


class ScreenGrabber:
    def grab(self, bbox: BoundingBox | None, monitor: int = ALL_MONITORS) -> Any:
        import mss
        from mss.exception import ScreenShotError
        from PIL import Image

        try:
            with mss.mss() as screen:
                shot = screen.grab(self._area(screen, bbox, monitor))
        except ScreenShotError as error:
            raise ActionExecutionError(f"Не вдалося зняти екран: {error}") from error
        return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")

    @staticmethod
    def _area(screen: Any, bbox: BoundingBox | None, monitor: int) -> dict[str, int]:
        if bbox is None:
            return dict(screen.monitors[min(monitor, len(screen.monitors) - 1)])
        left, top, right, bottom = bbox
        if right - left < 2 or bottom - top < 2:
            raise ActionExecutionError("Надто мала область для скріншота")
        return {"left": left, "top": top, "width": right - left, "height": bottom - top}


class ActiveWindowLocator(Protocol):
    def bounds(self) -> BoundingBox: ...


class Win32ActiveWindowLocator:
    def bounds(self) -> BoundingBox:
        if not is_windows():
            raise ActionExecutionError("Скріншот вікна доступний лише у Windows")
        import ctypes
        import ctypes.wintypes

        user32 = ctypes.windll.user32
        handle = user32.GetForegroundWindow()
        if not handle:
            raise ActionExecutionError("Не знайшов активного вікна")
        rect = ctypes.wintypes.RECT()
        dwm_extended_frame_bounds = 9
        result = ctypes.windll.dwmapi.DwmGetWindowAttribute(
            handle, dwm_extended_frame_bounds, ctypes.byref(rect), ctypes.sizeof(rect)
        )
        if result != 0:
            user32.GetWindowRect(handle, ctypes.byref(rect))
        return rect.left, rect.top, rect.right, rect.bottom


class ClipboardWriter(Protocol):
    def copy_image(self, image: Any) -> None: ...


class Win32ClipboardWriter:
    def copy_image(self, image: Any) -> None:
        if not is_windows():
            return
        import pywintypes
        import win32clipboard

        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, "BMP")
        dib = buffer.getvalue()[14:]
        try:
            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32clipboard.CF_DIB, dib)
            finally:
                win32clipboard.CloseClipboard()
        except pywintypes.error as error:
            logger.warning("Не вдалося скопіювати скріншот у буфер: %s", error)


class RegionSelector:
    def __init__(self, bus: EventBus, timeout_seconds: float) -> None:
        self._bus = bus
        self._timeout = timeout_seconds

    def select(self, preview: Path) -> Fraction | None:
        request_id = uuid.uuid4().hex
        response = self._bus.wait_for(
            RegionSelected,
            lambda event: event.request_id == request_id,
            timeout=self._timeout,
            trigger=RegionSelectionRequested(request_id, preview),
        )
        return response.fraction if response is not None else None


class ScreenshotService:
    def __init__(
        self,
        grabber: ScreenGrabber,
        windows: ActiveWindowLocator,
        clipboard: ClipboardWriter,
        regions: RegionSelector,
        directory: Path,
        settings: ScreenshotsSection,
    ) -> None:
        self._grabber = grabber
        self._windows = windows
        self._clipboard = clipboard
        self._regions = regions
        self._directory = directory
        self._settings = settings

    def capture(self, mode: ScreenshotMode) -> Path | None:
        if mode is ScreenshotMode.REGION:
            return self._capture_region()
        bbox = self._windows.bounds() if mode is ScreenshotMode.WINDOW else None
        return self._store(self._grabber.grab(bbox))

    def _capture_region(self) -> Path | None:
        image = self._grabber.grab(None, PRIMARY_MONITOR)
        preview = self._write_preview(image)
        try:
            fraction = self._regions.select(preview)
        finally:
            preview.unlink(missing_ok=True)
        if fraction is None:
            return None
        return self._store(image.crop(fraction_to_box(fraction, image.width, image.height)))

    @staticmethod
    def _write_preview(image: Any) -> Path:
        preview = image.copy()
        preview.thumbnail((PREVIEW_MAX_WIDTH, PREVIEW_MAX_WIDTH))
        handle = tempfile.NamedTemporaryFile(prefix="jarvis_region_", suffix=".jpg", delete=False)
        handle.close()
        path = Path(handle.name)
        preview.save(path, "JPEG", quality=PREVIEW_QUALITY)
        return path

    def _store(self, image: Any) -> Path:
        path = self._save(image)
        if self._settings.copy_to_clipboard:
            self._clipboard.copy_image(image)
        return path

    def _save(self, image: Any) -> Path:
        self._directory.mkdir(parents=True, exist_ok=True)
        path = self._directory / f"screenshot_{datetime.now():%Y%m%d_%H%M%S}.png"
        try:
            image.save(path, "PNG")
        except OSError as error:
            raise ActionExecutionError(f"Не вдалося зберегти скріншот: {error}") from error
        logger.info("Скріншот збережено: %s", path)
        return path


class ScreenshotsSkill:
    name = "screenshots"
    intents = frozenset({IntentName.SCREENSHOT})

    def __init__(self, service: ScreenshotService) -> None:
        self._service = service

    def handle(self, intent: Intent, context: DialogContext) -> SkillResult:
        mode = self._mode(intent.mode)
        try:
            path = self._service.capture(mode)
        except OSError as error:
            raise SkillError(f"Скріншот не вдався: {error}") from error
        if path is None:
            return SkillResult("Скріншот скасовано.", success=False)
        return SkillResult(f"Скріншот збережено: {path.name}.")

    @staticmethod
    def _mode(raw: str | None) -> ScreenshotMode:
        try:
            return ScreenshotMode(raw or ScreenshotMode.FULL.value)
        except ValueError:
            return ScreenshotMode.FULL
