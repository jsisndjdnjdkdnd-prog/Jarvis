from __future__ import annotations

import logging
import math
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from types import ModuleType
from typing import Protocol, TypeVar

from jarvis.core.context import DialogContext, SkillResult
from jarvis.core.errors import ActionExecutionError
from jarvis.core.intent import Intent, IntentName, SystemInfoKind
from jarvis.skills.formatting import format_duration_accusative, plural
from jarvis.skills.platform import is_windows

logger = logging.getLogger(__name__)

BYTES_IN_GB = 1024**3
PROBE_FAILED = "Не вдалося зчитати стан системи, сер."
NO_BATTERY = "Це стаціонарний комп'ютер, батареї немає, сер."
LOW_BATTERY_PERCENT = 25
BUSY_CPU_PERCENT = 85
BUSY_MEMORY_PERCENT = 90
FULL_DISK_PERCENT = 90
LONG_UPTIME_DAYS = 3
MINUTES_IN_DAY = 24 * 60

_Value = TypeVar("_Value")


@dataclass(frozen=True)
class BatteryStatus:
    percent: float
    plugged: bool
    seconds_left: int | None


@dataclass(frozen=True)
class MemoryStatus:
    percent: float
    used_gb: float
    total_gb: float


@dataclass(frozen=True)
class DiskStatus:
    percent: float
    free_gb: float


class SystemProbe(Protocol):
    def battery(self) -> BatteryStatus | None: ...

    def cpu_percent(self) -> float: ...

    def memory(self) -> MemoryStatus: ...

    def disk(self) -> DiskStatus: ...

    def boot_time(self) -> datetime: ...


def system_drive() -> str:
    if is_windows():
        return os.environ.get("SystemDrive", "C:") + "\\"
    return "/"


class PsutilProbe:
    def __init__(self, cpu_interval: float = 0.3, disk_path: str | None = None) -> None:
        self._cpu_interval = cpu_interval
        self._disk_path = disk_path

    def battery(self) -> BatteryStatus | None:
        return self._read(self._battery)

    def cpu_percent(self) -> float:
        return self._read(lambda psutil: float(psutil.cpu_percent(interval=self._cpu_interval)))

    def memory(self) -> MemoryStatus:
        return self._read(self._memory)

    def disk(self) -> DiskStatus:
        return self._read(self._disk)

    def boot_time(self) -> datetime:
        return self._read(lambda psutil: datetime.fromtimestamp(psutil.boot_time()))

    @staticmethod
    def _battery(psutil: ModuleType) -> BatteryStatus | None:
        sensors = getattr(psutil, "sensors_battery", None)
        status = sensors() if sensors is not None else None
        if status is None:
            return None
        plugged = bool(status.power_plugged)
        seconds = status.secsleft
        known = isinstance(seconds, int | float) and seconds > 0 and not plugged
        return BatteryStatus(
            percent=float(status.percent), plugged=plugged, seconds_left=int(seconds) if known else None
        )

    @staticmethod
    def _memory(psutil: ModuleType) -> MemoryStatus:
        memory = psutil.virtual_memory()
        used = memory.total - memory.available
        return MemoryStatus(
            percent=float(memory.percent), used_gb=used / BYTES_IN_GB, total_gb=memory.total / BYTES_IN_GB
        )

    def _disk(self, psutil: ModuleType) -> DiskStatus:
        usage = psutil.disk_usage(self._disk_path or system_drive())
        return DiskStatus(percent=float(usage.percent), free_gb=usage.free / BYTES_IN_GB)

    @staticmethod
    def _read(reader: Callable[[ModuleType], _Value]) -> _Value:
        try:
            import psutil
        except ImportError as error:
            raise ActionExecutionError(PROBE_FAILED) from error
        try:
            return reader(psutil)
        except (OSError, psutil.Error) as error:
            logger.warning("psutil не зміг прочитати стан системи: %s", error)
            raise ActionExecutionError(PROBE_FAILED) from error


def _whole(value: float) -> int:
    return math.floor(value + 0.5)


def _gigabytes(value: float) -> str:
    if value >= 100:
        return str(_whole(value))
    text = f"{value:.1f}".replace(".", ",")
    return text[:-2] if text.endswith(",0") else text


def format_uptime(seconds: float) -> str:
    total_minutes = int(max(0.0, seconds) // 60)
    if total_minutes < 1:
        return "менше хвилини"
    days, minutes = divmod(total_minutes, MINUTES_IN_DAY)
    parts: list[str] = []
    if days:
        parts.append(f"{days} {plural(days, 'день', 'дні', 'днів')}")
    if minutes:
        parts.append(format_duration_accusative(minutes * 60))
    return " ".join(parts)


class SystemInfoSkill:
    name = "system_info"
    intents = frozenset({IntentName.SYSTEM_INFO})

    def __init__(self, probe: SystemProbe, clock: Callable[[], datetime] = datetime.now) -> None:
        self._probe = probe
        self._clock = clock

    def handle(self, intent: Intent, context: DialogContext) -> SkillResult:
        reporters: dict[SystemInfoKind, Callable[[], str]] = {
            SystemInfoKind.BATTERY: self._battery,
            SystemInfoKind.CPU: self._cpu,
            SystemInfoKind.MEMORY: self._memory,
            SystemInfoKind.DISK: self._disk,
            SystemInfoKind.UPTIME: self._uptime,
            SystemInfoKind.ALL: self._overview,
        }
        return SkillResult(reporters[self._kind(intent.mode)](), learnable=True)

    @staticmethod
    def _kind(mode: str | None) -> SystemInfoKind:
        try:
            return SystemInfoKind(mode) if mode else SystemInfoKind.ALL
        except ValueError:
            return SystemInfoKind.ALL

    def _battery(self) -> str:
        battery = self._probe.battery()
        if battery is None:
            return NO_BATTERY
        percent = min(100, _whole(battery.percent))
        if battery.plugged:
            if percent >= 100:
                return "Заряд 100%, батарея повністю заряджена."
            return f"Заряд {percent}%, заряджається."
        summary = f"Заряд {percent}%"
        if battery.seconds_left:
            minutes = max(1, _whole(battery.seconds_left / 60))
            summary += f", вистачить приблизно на {format_duration_accusative(minutes * 60)}"
        if percent <= LOW_BATTERY_PERCENT:
            return f"{summary}. Раджу підключити зарядку, сер."
        return f"{summary}."

    def _cpu(self) -> str:
        percent = _whole(self._probe.cpu_percent())
        summary = f"Процесор завантажений на {percent}%."
        if percent >= BUSY_CPU_PERCENT:
            return f"{summary} Він працює на межі, сер."
        return summary

    def _memory(self) -> str:
        memory = self._probe.memory()
        percent = _whole(memory.percent)
        summary = (
            f"Використано {_gigabytes(memory.used_gb)} з {_whole(memory.total_gb)} ГБ пам'яті — {percent}%."
        )
        if percent >= BUSY_MEMORY_PERCENT:
            return f"{summary} Варто закрити щось зайве, сер."
        return summary

    def _disk(self) -> str:
        disk = self._probe.disk()
        percent = _whole(disk.percent)
        summary = f"На системному диску вільно {_gigabytes(disk.free_gb)} ГБ, зайнято {percent}%."
        if percent >= FULL_DISK_PERCENT:
            return f"{summary} Час трохи прибрати, сер."
        return summary

    def _uptime(self) -> str:
        seconds = (self._clock() - self._probe.boot_time()).total_seconds()
        summary = f"Комп'ютер працює {format_uptime(seconds)}."
        if seconds >= LONG_UPTIME_DAYS * MINUTES_IN_DAY * 60:
            return f"{summary} Можливо, йому варто перезавантажитися, сер."
        return summary

    def _overview(self) -> str:
        memory = self._probe.memory()
        parts = [
            f"Процесор завантажений на {_whole(self._probe.cpu_percent())}%.",
            f"Пам'ять зайнята на {_whole(memory.percent)}%.",
        ]
        battery = self._probe.battery()
        if battery is not None:
            charging = ", заряджається" if battery.plugged and battery.percent < 99.5 else ""
            parts.append(f"Заряд {min(100, _whole(battery.percent))}%{charging}.")
        return " ".join(parts)
