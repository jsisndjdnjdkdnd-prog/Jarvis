from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

import psutil
from rapidfuzz import fuzz

from jarvis.core.errors import ActionExecutionError
from jarvis.core.models import Program, ProgramKind
from jarvis.nlu.text_normalizer import TextNormalizer
from jarvis.nlu.transliteration import cyrillic_to_latin
from jarvis.skills.platform import ShellOpener

logger = logging.getLogger(__name__)

PROCESS_MATCH_THRESHOLD = 86.0
PROTECTED_PROCESSES: frozenset[str] = frozenset(
    {"explorer.exe", "csrss.exe", "winlogon.exe", "svchost.exe", "lsass.exe", "system", "dwm.exe", "services.exe"}
)

KNOWN_FOLDERS: dict[str, str] = {
    "завантаження": "Downloads", "завантажень": "Downloads", "загрузки": "Downloads", "downloads": "Downloads",
    "документи": "Documents", "документів": "Documents", "документы": "Documents", "documents": "Documents",
    "робочий стіл": "Desktop", "рабочий стол": "Desktop", "desktop": "Desktop",
    "зображення": "Pictures", "картинки": "Pictures", "фото": "Pictures", "pictures": "Pictures",
    "музика": "Music", "музики": "Music", "музыка": "Music", "music": "Music",
    "відео": "Videos", "видео": "Videos", "videos": "Videos",
    "домашню": "", "домашня": "", "home": "",
}

KNOWN_SITES: dict[str, str] = {
    "ютуб": "https://www.youtube.com", "youtube": "https://www.youtube.com",
    "гугл": "https://www.google.com", "google": "https://www.google.com",
    "гітхаб": "https://github.com", "github": "https://github.com",
    "вікіпедія": "https://uk.wikipedia.org", "wikipedia": "https://uk.wikipedia.org",
    "пошта": "https://mail.google.com", "gmail": "https://mail.google.com", "джимейл": "https://mail.google.com",
    "саундклауд": "https://soundcloud.com", "soundcloud": "https://soundcloud.com",
    "твіч": "https://www.twitch.tv", "twitch": "https://www.twitch.tv",
    "реддіт": "https://www.reddit.com", "reddit": "https://www.reddit.com",
    "інстаграм": "https://www.instagram.com", "instagram": "https://www.instagram.com",
    "твіттер": "https://x.com", "twitter": "https://x.com",
    "нетфлікс": "https://www.netflix.com", "netflix": "https://www.netflix.com",
    "чат гпт": "https://chatgpt.com", "chatgpt": "https://chatgpt.com",
    "перекладач": "https://translate.google.com", "translate": "https://translate.google.com",
}


@dataclass(frozen=True)
class CloseReport:
    terminated: int
    killed: int

    @property
    def total(self) -> int:
        return self.terminated + self.killed


class ProgramLauncher:
    def __init__(self, opener: ShellOpener) -> None:
        self._opener = opener

    def launch(self, program: Program) -> None:
        logger.info("Запуск %s (%s)", program.name, program.launch_target)
        if program.kind is ProgramKind.UWP:
            self._opener.open_uwp(program.launch_target)
            return
        self._opener.open(program.launch_target)


class ProcessCloser:
    def __init__(self, timeout_seconds: float) -> None:
        self._timeout = timeout_seconds

    def close_program(self, program: Program) -> CloseReport:
        names = set(program.process_names) or self._names_from_target(program)
        processes = self._find_by_names(names) if names else []
        if not processes:
            processes = self._find_fuzzy(program.name)
        return self._stop(processes)

    def close_by_query(self, query: str) -> CloseReport:
        return self._stop(self._find_fuzzy(query))

    @staticmethod
    def _names_from_target(program: Program) -> set[str]:
        target = program.launch_target.lower()
        if target.endswith(".exe"):
            return {Path(target).name}
        return set()

    @staticmethod
    def _find_by_names(names: Iterable[str]) -> list[psutil.Process]:
        wanted = {name.lower() for name in names} - PROTECTED_PROCESSES
        found: list[psutil.Process] = []
        for process in psutil.process_iter(["name"]):
            name = (process.info.get("name") or "").lower()
            if name in wanted:
                found.append(process)
        return found

    @staticmethod
    def _find_fuzzy(query: str) -> list[psutil.Process]:
        target = cyrillic_to_latin(TextNormalizer.basic(query)).replace(" ", "")
        if len(target) < 3:
            return []
        found: list[psutil.Process] = []
        for process in psutil.process_iter(["name"]):
            name = (process.info.get("name") or "").lower()
            if not name or name in PROTECTED_PROCESSES:
                continue
            stem = Path(name).stem.replace(" ", "")
            if fuzz.ratio(stem, target) >= PROCESS_MATCH_THRESHOLD or (len(target) >= 5 and target in stem):
                found.append(process)
        return found

    def _stop(self, processes: list[psutil.Process]) -> CloseReport:
        if not processes:
            return CloseReport(0, 0)
        for process in processes:
            self._safe(process.terminate)
        _, alive = psutil.wait_procs(processes, timeout=self._timeout)
        for process in alive:
            self._safe(process.kill)
        return CloseReport(terminated=len(processes) - len(alive), killed=len(alive))

    @staticmethod
    def _safe(operation: Callable[[], None]) -> None:
        try:
            operation()
        except psutil.NoSuchProcess:
            return
        except psutil.AccessDenied as error:
            logger.warning("Немає прав завершити процес: %s", error)


class FolderResolver:
    def resolve(self, name: str) -> Path | None:
        normalized = TextNormalizer.basic(name)
        if normalized in KNOWN_FOLDERS:
            return self._known(KNOWN_FOLDERS[normalized])
        candidate = Path(name).expanduser()
        if candidate.is_dir():
            return candidate
        for key, folder in KNOWN_FOLDERS.items():
            if fuzz.ratio(normalized, key) >= 85:
                return self._known(folder)
        return None

    @staticmethod
    def _known(folder: str) -> Path:
        home = Path(os.environ.get("USERPROFILE") or Path.home())
        return home / folder if folder else home


class UrlResolver:
    def resolve(self, target: str) -> str:
        cleaned = TextNormalizer.basic(target)
        if ShellOpener.looks_like_url(target):
            return target
        if cleaned in KNOWN_SITES:
            return KNOWN_SITES[cleaned]
        for key, url in KNOWN_SITES.items():
            if fuzz.ratio(cleaned, key) >= 85:
                return url
        if "." in cleaned and " " not in cleaned:
            return f"https://{cleaned}"
        slug = cyrillic_to_latin(cleaned).replace(" ", "")
        if not slug:
            raise ActionExecutionError("Не зрозумів адресу сайту")
        return f"https://www.{slug}.com"
