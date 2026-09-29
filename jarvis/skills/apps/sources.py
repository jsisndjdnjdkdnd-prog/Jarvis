from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote

from jarvis.core.models import ProgramKind
from jarvis.skills.apps.known_aliases import SYSTEM_PROGRAMS
from jarvis.skills.platform import hidden_process_flags, is_windows

logger = logging.getLogger(__name__)

NOISE_MARKERS: tuple[str, ...] = (
    "unins", "uninstall", "видалити", "удалить", "setup", "install", "update", "updater",
    "crash", "helper", "report", "elevat", "service", "svc", "notif", "redist", "vc_redist",
    "dotnet", "readme", "help", "license", "documentation", "support", "repair", "config",
    "diagnos", "feedback", "debug", "migrat", "bugreport", "prereq", "cleanup",
)
UNINSTALL_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
UNINSTALL_WOW_KEY = r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"
APP_PATHS_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
STEAM_KEY = r"Software\Valve\Steam"
MAX_GAME_EXECUTABLES = 6
_VDF_TOKEN = re.compile(r'"((?:[^"\\]|\\.)*)"|([{}])')


@dataclass(frozen=True)
class DiscoveredProgram:
    name: str
    launch_target: str
    kind: ProgramKind
    source: str
    process_names: tuple[str, ...] = ()
    aliases: tuple[str, ...] = field(default_factory=tuple)


class ProgramSource(Protocol):
    @property
    def name(self) -> str: ...

    def discover(self) -> Iterator[DiscoveredProgram]: ...


def is_noise(name: str) -> bool:
    lowered = name.lower()
    return any(marker in lowered for marker in NOISE_MARKERS)


def executable_names(path: str | None) -> tuple[str, ...]:
    if not path or not path.lower().endswith(".exe"):
        return ()
    return (Path(path).name.lower(),)


def find_executables(root: Path, depth: int, limit: int) -> list[Path]:
    found: list[Path] = []
    if not root.is_dir():
        return found
    for current, directories, files in os.walk(root):
        level = len(Path(current).relative_to(root).parts)
        if level >= depth:
            directories.clear()
        for file_name in files:
            if file_name.lower().endswith(".exe") and not is_noise(file_name):
                found.append(Path(current) / file_name)
                if len(found) >= limit:
                    return found
    return found


def parse_vdf(text: str) -> dict[str, Any]:
    root: dict[str, Any] = {}
    stack: list[dict[str, Any]] = [root]
    key: str | None = None
    for quoted, brace in _VDF_TOKEN.findall(text):
        if brace == "{":
            child: dict[str, Any] = {}
            stack[-1][key or ""] = child
            stack.append(child)
            key = None
        elif brace == "}":
            if len(stack) > 1:
                stack.pop()
            key = None
        elif key is None:
            key = quoted
        else:
            stack[-1][key] = quoted.replace("\\\\", "\\")
            key = None
    return root


class SystemProgramsSource:
    name = "system"

    def discover(self) -> Iterator[DiscoveredProgram]:
        for program in SYSTEM_PROGRAMS:
            yield DiscoveredProgram(
                name=program.name,
                launch_target=program.launch_target,
                kind=program.kind,
                source=self.name,
                process_names=program.process_names,
                aliases=program.aliases,
            )


class ShortcutResolver:
    def __init__(self) -> None:
        self._shell: Any = None

    def resolve(self, shortcut: Path) -> str | None:
        import pywintypes

        try:
            return str(self._get_shell().CreateShortCut(str(shortcut)).Targetpath) or None
        except (pywintypes.com_error, pywintypes.error, OSError) as error:
            logger.debug("Не вдалося прочитати ярлик %s: %s", shortcut, error)
            return None

    def _get_shell(self) -> Any:
        if self._shell is None:
            import win32com.client

            self._shell = win32com.client.Dispatch("WScript.Shell")
        return self._shell


class StartMenuSource:
    name = "start_menu"

    def __init__(self, resolver: ShortcutResolver) -> None:
        self._resolver = resolver

    def discover(self) -> Iterator[DiscoveredProgram]:
        for root in self._roots():
            for shortcut in root.rglob("*.lnk"):
                if is_noise(shortcut.stem):
                    continue
                target = self._resolver.resolve(shortcut)
                if target is not None and is_noise(Path(target).name):
                    continue
                yield DiscoveredProgram(
                    name=shortcut.stem,
                    launch_target=str(shortcut),
                    kind=ProgramKind.SHORTCUT,
                    source=self.name,
                    process_names=executable_names(target),
                )

    @staticmethod
    def _roots() -> list[Path]:
        candidates = [
            Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "Microsoft/Windows/Start Menu/Programs",
            Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
        ]
        return [path for path in candidates if path.is_dir()]


class ProgramFilesSource:
    name = "program_files"

    def __init__(self, depth: int) -> None:
        self._depth = depth

    def discover(self) -> Iterator[DiscoveredProgram]:
        for root in self._roots():
            for vendor_dir in self._children(root):
                for executable in find_executables(vendor_dir, self._depth, limit=15):
                    yield DiscoveredProgram(
                        name=executable.stem,
                        launch_target=str(executable),
                        kind=ProgramKind.EXECUTABLE,
                        source=self.name,
                        process_names=(executable.name.lower(),),
                        aliases=(vendor_dir.name,),
                    )

    @staticmethod
    def _children(root: Path) -> list[Path]:
        try:
            return [child for child in root.iterdir() if child.is_dir() and not is_noise(child.name)]
        except OSError:
            return []

    @staticmethod
    def _roots() -> list[Path]:
        candidates = [
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")),
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")),
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs",
        ]
        return [path for path in candidates if path.is_dir()]


class RegistryReader:
    def subkeys(self, hive: int, path: str) -> Iterator[str]:
        import winreg

        try:
            with winreg.OpenKey(hive, path) as key:
                index = 0
                while True:
                    try:
                        yield winreg.EnumKey(key, index)
                    except OSError:
                        return
                    index += 1
        except OSError:
            return

    def values(self, hive: int, path: str) -> dict[str, Any]:
        import winreg

        result: dict[str, Any] = {}
        try:
            with winreg.OpenKey(hive, path) as key:
                index = 0
                while True:
                    try:
                        name, value, _ = winreg.EnumValue(key, index)
                    except OSError:
                        return result
                    result[name] = value
                    index += 1
        except OSError:
            return result


class AppPathsSource:
    name = "app_paths"

    def __init__(self, registry: RegistryReader) -> None:
        self._registry = registry

    def discover(self) -> Iterator[DiscoveredProgram]:
        import winreg

        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for subkey in self._registry.subkeys(hive, APP_PATHS_KEY):
                values = self._registry.values(hive, f"{APP_PATHS_KEY}\\{subkey}")
                executable = str(values.get("", "")).strip('"')
                if not executable or is_noise(subkey) or not Path(executable).exists():
                    continue
                yield DiscoveredProgram(
                    name=Path(subkey).stem,
                    launch_target=executable,
                    kind=ProgramKind.EXECUTABLE,
                    source=self.name,
                    process_names=executable_names(executable),
                )


class UninstallSource:
    name = "uninstall"

    def __init__(self, registry: RegistryReader) -> None:
        self._registry = registry

    def discover(self) -> Iterator[DiscoveredProgram]:
        import winreg

        locations = (
            (winreg.HKEY_LOCAL_MACHINE, UNINSTALL_KEY),
            (winreg.HKEY_LOCAL_MACHINE, UNINSTALL_WOW_KEY),
            (winreg.HKEY_CURRENT_USER, UNINSTALL_KEY),
        )
        for hive, path in locations:
            for subkey in self._registry.subkeys(hive, path):
                program = self._program(self._registry.values(hive, f"{path}\\{subkey}"))
                if program is not None:
                    yield program

    def _program(self, values: dict[str, Any]) -> DiscoveredProgram | None:
        name = str(values.get("DisplayName", "")).strip()
        if not name or values.get("SystemComponent") == 1 or values.get("ParentKeyName"):
            return None
        executable = self._executable(values)
        if executable is None or is_noise(Path(executable).name):
            return None
        return DiscoveredProgram(
            name=name,
            launch_target=executable,
            kind=ProgramKind.EXECUTABLE,
            source=self.name,
            process_names=executable_names(executable),
        )

    @staticmethod
    def _executable(values: dict[str, Any]) -> str | None:
        icon = str(values.get("DisplayIcon", "")).split(",")[0].strip().strip('"')
        if icon.lower().endswith(".exe") and Path(icon).exists():
            return icon
        return None


class SteamSource:
    name = "steam"

    def __init__(self, registry: RegistryReader, depth: int) -> None:
        self._registry = registry
        self._depth = depth

    def discover(self) -> Iterator[DiscoveredProgram]:
        steam_root = self._steam_root()
        if steam_root is None:
            return
        for library in self._libraries(steam_root):
            yield from self._games(library / "steamapps")

    def _steam_root(self) -> Path | None:
        import winreg

        values = self._registry.values(winreg.HKEY_CURRENT_USER, STEAM_KEY)
        candidates = [
            str(values.get("SteamPath", "")),
            os.path.join(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"), "Steam"),
        ]
        for candidate in candidates:
            if candidate and Path(candidate).is_dir():
                return Path(candidate)
        return None

    @staticmethod
    def _libraries(steam_root: Path) -> list[Path]:
        libraries = [steam_root]
        vdf_file = steam_root / "steamapps" / "libraryfolders.vdf"
        if not vdf_file.exists():
            return libraries
        data = parse_vdf(vdf_file.read_text(encoding="utf-8", errors="ignore"))
        folders = data.get("libraryfolders") or data.get("LibraryFolders") or {}
        for entry in folders.values():
            path = entry.get("path") if isinstance(entry, dict) else entry
            if isinstance(path, str) and Path(path).is_dir() and Path(path) not in libraries:
                libraries.append(Path(path))
        return libraries

    def _games(self, steamapps: Path) -> Iterator[DiscoveredProgram]:
        for manifest in steamapps.glob("appmanifest_*.acf"):
            state = parse_vdf(manifest.read_text(encoding="utf-8", errors="ignore")).get("AppState", {})
            app_id = state.get("appid")
            name = state.get("name")
            if not app_id or not name or is_noise(name) or "redistributable" in name.lower():
                continue
            install_dir = steamapps / "common" / str(state.get("installdir", ""))
            executables = find_executables(install_dir, self._depth, MAX_GAME_EXECUTABLES)
            yield DiscoveredProgram(
                name=name,
                launch_target=f"steam://rungameid/{app_id}",
                kind=ProgramKind.STEAM,
                source=self.name,
                process_names=tuple(executable.name.lower() for executable in executables),
            )


class EpicGamesSource:
    name = "epic"

    def discover(self) -> Iterator[DiscoveredProgram]:
        manifests = (
            Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
            / "Epic/EpicGamesLauncher/Data/Manifests"
        )
        if not manifests.is_dir():
            return
        for item in manifests.glob("*.item"):
            program = self._program(item)
            if program is not None:
                yield program

    def _program(self, item: Path) -> DiscoveredProgram | None:
        try:
            data = json.loads(item.read_text(encoding="utf-8", errors="ignore"))
        except (OSError, json.JSONDecodeError):
            return None
        name = data.get("DisplayName")
        app_name = data.get("AppName")
        if not name or not app_name:
            return None
        identifier = ":".join(
            part for part in (data.get("CatalogNamespace"), data.get("CatalogItemId"), app_name) if part
        )
        executable = str(data.get("LaunchExecutable", ""))
        return DiscoveredProgram(
            name=name,
            launch_target=f"com.epicgames.launcher://apps/{quote(identifier, safe='')}?action=launch&silent=true",
            kind=ProgramKind.EPIC,
            source=self.name,
            process_names=(Path(executable).name.lower(),) if executable else (),
        )


class UwpAppsSource:
    name = "uwp"

    def discover(self) -> Iterator[DiscoveredProgram]:
        for entry in self._start_apps():
            name = str(entry.get("Name", "")).strip()
            app_id = str(entry.get("AppID", "")).strip()
            if not name or not app_id or is_noise(name):
                continue
            yield DiscoveredProgram(
                name=name,
                launch_target=app_id,
                kind=ProgramKind.UWP,
                source=self.name,
                process_names=executable_names(app_id),
            )

    @staticmethod
    def _start_apps() -> list[dict[str, Any]]:
        if not is_windows():
            return []
        command = [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-StartApps | ConvertTo-Json -Compress",
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                timeout=30,
                check=True,
                creationflags=hidden_process_flags(),
            )
        except (OSError, subprocess.SubprocessError) as error:
            logger.warning("Get-StartApps не спрацював: %s", error)
            return []
        try:
            data = json.loads(completed.stdout.decode("utf-8", errors="ignore") or "[]")
        except json.JSONDecodeError:
            return []
        return data if isinstance(data, list) else [data]
