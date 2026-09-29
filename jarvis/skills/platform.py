from __future__ import annotations

import logging
import os
import subprocess
import sys
import webbrowser
from pathlib import Path

from jarvis.core.errors import ActionExecutionError, PlatformNotSupportedError

logger = logging.getLogger(__name__)

URL_SCHEMES: tuple[str, ...] = ("http://", "https://", "steam://", "com.epicgames.launcher://", "ms-settings:", "mailto:")


def is_windows() -> bool:
    return sys.platform == "win32"


def require_windows(feature: str) -> None:
    if not is_windows():
        raise PlatformNotSupportedError(f"{feature} доступно лише у Windows")


def hidden_process_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


class ShellOpener:
    def open(self, target: str) -> None:
        if not target.strip():
            raise ActionExecutionError("Порожня ціль запуску")
        try:
            self._open(target.strip())
        except OSError as error:
            raise ActionExecutionError(f"Не вдалося відкрити «{target}»: {error}") from error

    def open_uwp(self, app_id: str) -> None:
        require_windows("Запуск UWP-застосунків")
        try:
            subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{app_id}"])
        except OSError as error:
            raise ActionExecutionError(f"Не вдалося запустити {app_id}: {error}") from error

    def run_shell(self, command: str) -> None:
        try:
            subprocess.Popen(command, shell=True, creationflags=hidden_process_flags())
        except OSError as error:
            raise ActionExecutionError(f"Команда не виконалась: {error}") from error

    def _open(self, target: str) -> None:
        if is_windows():
            os.startfile(target)
            return
        if target.startswith(("http://", "https://")):
            webbrowser.open(target)
            return
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        subprocess.Popen([opener, target])

    @staticmethod
    def looks_like_url(target: str) -> bool:
        return target.lower().startswith(URL_SCHEMES)

    @staticmethod
    def looks_like_path(target: str) -> bool:
        return Path(target).expanduser().exists()
