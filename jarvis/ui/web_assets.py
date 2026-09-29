from __future__ import annotations

import re
from pathlib import Path

from jarvis.core.errors import ConfigError

WEB_DIR = Path(__file__).resolve().parent / "web"
_STYLESHEET = re.compile(r'<link rel="stylesheet" href="([\w\-.]+\.css)">')
_SCRIPT = re.compile(r'<script src="([\w\-.]+\.js)"></script>')


class WebAssets:
    def __init__(self, root: Path = WEB_DIR) -> None:
        self._root = root

    def page(self, name: str, replacements: dict[str, str] | None = None) -> str:
        html = self._read(f"{name}.html")
        html = _STYLESHEET.sub(lambda match: f"<style>{self._read(match.group(1))}</style>", html)
        html = _SCRIPT.sub(lambda match: f"<script>{self._read(match.group(1))}</script>", html)
        for key, value in (replacements or {}).items():
            html = html.replace(key, value)
        return html

    def _read(self, relative: str) -> str:
        path = self._root / relative
        try:
            return path.read_text(encoding="utf-8")
        except OSError as error:
            raise ConfigError(f"Не знайдено файл інтерфейсу {path}: {error}") from error
