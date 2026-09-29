from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any, Protocol

from jarvis.core.errors import ActionExecutionError
from jarvis.skills.platform import require_windows

logger = logging.getLogger(__name__)

FEATURE = "Керування вікнами"
SW_MAXIMIZE = 3
SW_MINIMIZE = 6
SW_RESTORE = 9
WM_CLOSE = 0x0010
VK_MENU = 0x12
KEYEVENTF_KEYUP = 0x2
CLASS_NAME_LIMIT = 256
SHELL_WINDOW_CLASSES: frozenset[str] = frozenset({"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"})


class WindowManager(Protocol):
    def find(self, title_keywords: Sequence[str]) -> int | None: ...

    def focus(self, handle: int) -> bool: ...

    def foreground_title(self) -> str: ...

    def minimize_foreground(self) -> None: ...

    def maximize_foreground(self) -> None: ...

    def restore_foreground(self) -> None: ...

    def close_foreground(self) -> None: ...


def title_matches(title: str, title_keywords: Sequence[str]) -> bool:
    lowered = title.casefold()
    keywords = [keyword.strip().casefold() for keyword in title_keywords]
    return any(keyword and keyword in lowered for keyword in keywords)


class Win32WindowManager:
    def __init__(self) -> None:
        self._user32: Any = None
        self._enum_proc: Any = None

    def find(self, title_keywords: Sequence[str]) -> int | None:
        require_windows(FEATURE)
        for handle, title in self._visible_windows():
            if title_matches(title, title_keywords):
                return handle
        return None

    def focus(self, handle: int) -> bool:
        require_windows(FEATURE)
        user32 = self._api()
        if user32.IsIconic(handle):
            user32.ShowWindow(handle, SW_RESTORE)
        user32.keybd_event(VK_MENU, 0, 0, 0)
        user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
        user32.SetForegroundWindow(handle)
        user32.BringWindowToTop(handle)
        focused = (user32.GetForegroundWindow() or 0) == handle
        if not focused:
            logger.info("Вікно %s не вдалося вивести на передній план", handle)
        return focused

    def foreground_title(self) -> str:
        require_windows(FEATURE)
        handle = self._api().GetForegroundWindow() or 0
        return self._title(handle) if handle else ""

    def minimize_foreground(self) -> None:
        require_windows(FEATURE)
        self._api().ShowWindow(self._foreground(), SW_MINIMIZE)

    def maximize_foreground(self) -> None:
        require_windows(FEATURE)
        self._api().ShowWindow(self._foreground(), SW_MAXIMIZE)

    def restore_foreground(self) -> None:
        require_windows(FEATURE)
        self._api().ShowWindow(self._foreground(), SW_RESTORE)

    def close_foreground(self) -> None:
        require_windows(FEATURE)
        if not self._api().PostMessageW(self._foreground(), WM_CLOSE, 0, 0):
            raise ActionExecutionError("Не вдалося закрити вікно, сер.")

    def _foreground(self) -> int:
        handle = self._api().GetForegroundWindow() or 0
        if not handle or self._class_name(handle) in SHELL_WINDOW_CLASSES:
            raise ActionExecutionError("Не бачу активного вікна, сер.")
        return int(handle)

    def _visible_windows(self) -> list[tuple[int, str]]:
        user32 = self._api()
        windows: list[tuple[int, str]] = []

        def collect(handle: int | None, _: int) -> bool:
            if handle and user32.IsWindowVisible(handle):
                title = self._title(handle)
                if title:
                    windows.append((int(handle), title))
            return True

        if not user32.EnumWindows(self._enum_proc(collect), 0):
            raise ActionExecutionError("Не вдалося переглянути відкриті вікна, сер.")
        return windows

    def _title(self, handle: int) -> str:
        import ctypes

        user32 = self._api()
        length = user32.GetWindowTextLengthW(handle)
        if length <= 0:
            return ""
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(handle, buffer, length + 1)
        return buffer.value

    def _class_name(self, handle: int) -> str:
        import ctypes

        buffer = ctypes.create_unicode_buffer(CLASS_NAME_LIMIT)
        self._api().GetClassNameW(handle, buffer, CLASS_NAME_LIMIT)
        return buffer.value

    def _api(self) -> Any:
        if self._user32 is None:
            self._user32, self._enum_proc = _load_user32()
        return self._user32


def _load_user32() -> tuple[Any, Any]:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    prototypes: dict[str, tuple[list[Any], Any]] = {
        "EnumWindows": ([enum_proc, wintypes.LPARAM], wintypes.BOOL),
        "IsWindowVisible": ([wintypes.HWND], wintypes.BOOL),
        "IsIconic": ([wintypes.HWND], wintypes.BOOL),
        "GetWindowTextLengthW": ([wintypes.HWND], ctypes.c_int),
        "GetWindowTextW": ([wintypes.HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int),
        "GetClassNameW": ([wintypes.HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int),
        "ShowWindow": ([wintypes.HWND, ctypes.c_int], wintypes.BOOL),
        "SetForegroundWindow": ([wintypes.HWND], wintypes.BOOL),
        "BringWindowToTop": ([wintypes.HWND], wintypes.BOOL),
        "GetForegroundWindow": ([], wintypes.HWND),
        "PostMessageW": ([wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM], wintypes.BOOL),
        "keybd_event": ([ctypes.c_ubyte, ctypes.c_ubyte, wintypes.DWORD, ctypes.c_size_t], None),
    }
    for name, (argtypes, restype) in prototypes.items():
        function = getattr(user32, name)
        function.argtypes = argtypes
        function.restype = restype
    return user32, enum_proc
