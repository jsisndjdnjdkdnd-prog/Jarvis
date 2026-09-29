from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol

from jarvis.core.config import SystemSection
from jarvis.core.context import DialogContext, PendingConfirmation, SkillResult
from jarvis.core.errors import ActionExecutionError
from jarvis.core.intent import Intent, IntentName
from jarvis.skills.formatting import WEEKDAYS, format_date, format_time
from jarvis.skills.platform import ShellOpener, require_windows

logger = logging.getLogger(__name__)


class VolumeController(Protocol):
    def get(self) -> int: ...

    def set(self, percent: int) -> None: ...

    def set_muted(self, muted: bool) -> None: ...


class PycawVolumeController:
    def __init__(self) -> None:
        self._local = threading.local()

    def get(self) -> int:
        return int(round(self._endpoint().GetMasterVolumeLevelScalar() * 100))

    def set(self, percent: int) -> None:
        self._endpoint().SetMasterVolumeLevelScalar(max(0, min(100, percent)) / 100.0, None)

    def set_muted(self, muted: bool) -> None:
        self._endpoint().SetMute(int(muted), None)

    def _endpoint(self) -> Any:
        require_windows("Керування гучністю")
        endpoint = getattr(self._local, "endpoint", None)
        if endpoint is not None:
            return endpoint
        import comtypes

        comtypes.CoInitialize()
        endpoint = self._activate()
        self._local.endpoint = endpoint
        return endpoint

    @staticmethod
    def _activate() -> Any:
        from ctypes import POINTER, cast

        from comtypes import CLSCTX_ALL, COMError
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

        try:
            speakers = AudioUtilities.GetSpeakers()
            direct = getattr(speakers, "EndpointVolume", None)
            if direct is not None:
                return direct
            interface = speakers.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            return cast(interface, POINTER(IAudioEndpointVolume))
        except (COMError, OSError) as error:
            raise ActionExecutionError(f"Аудіопристрій недоступний: {error}") from error


class PowerController(Protocol):
    def lock(self) -> None: ...

    def shutdown(self, delay_seconds: int) -> None: ...

    def restart(self, delay_seconds: int) -> None: ...


class WindowsPowerController:
    def __init__(self, opener: ShellOpener) -> None:
        self._opener = opener

    def lock(self) -> None:
        require_windows("Блокування ПК")
        import ctypes

        if not ctypes.windll.user32.LockWorkStation():
            raise ActionExecutionError("Не вдалося заблокувати комп'ютер")

    def shutdown(self, delay_seconds: int) -> None:
        require_windows("Вимкнення ПК")
        self._opener.run_shell(f"shutdown /s /t {int(delay_seconds)}")

    def restart(self, delay_seconds: int) -> None:
        require_windows("Перезавантаження ПК")
        self._opener.run_shell(f"shutdown /r /t {int(delay_seconds)}")


class SystemSkill:
    name = "system"
    intents = frozenset(
        {
            IntentName.VOLUME_UP,
            IntentName.VOLUME_DOWN,
            IntentName.VOLUME_SET,
            IntentName.MUTE,
            IntentName.UNMUTE,
            IntentName.LOCK_PC,
            IntentName.SHUTDOWN_PC,
            IntentName.RESTART_PC,
            IntentName.TIME_NOW,
            IntentName.DATE_NOW,
        }
    )

    def __init__(
        self,
        volume: VolumeController,
        power: PowerController,
        settings: SystemSection,
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._volume = volume
        self._power = power
        self._settings = settings
        self._clock = clock

    def handle(self, intent: Intent, context: DialogContext) -> SkillResult:
        handlers: dict[IntentName, Callable[[Intent], SkillResult]] = {
            IntentName.VOLUME_UP: lambda item: self._shift_volume(item.amount or self._settings.volume_step),
            IntentName.VOLUME_DOWN: lambda item: self._shift_volume(-(item.amount or self._settings.volume_step)),
            IntentName.VOLUME_SET: self._set_volume,
            IntentName.MUTE: lambda _: self._mute(True),
            IntentName.UNMUTE: lambda _: self._mute(False),
            IntentName.LOCK_PC: lambda _: self._lock(),
            IntentName.SHUTDOWN_PC: lambda _: self._confirm_power("вимкнути", self._power.shutdown),
            IntentName.RESTART_PC: lambda _: self._confirm_power("перезавантажити", self._power.restart),
            IntentName.TIME_NOW: lambda _: self._time(),
            IntentName.DATE_NOW: lambda _: self._date(),
        }
        return handlers[intent.name](intent)

    def _shift_volume(self, delta: int) -> SkillResult:
        target = max(0, min(100, self._volume.get() + delta))
        self._volume.set(target)
        return SkillResult(f"Гучність {target}%.")

    def _set_volume(self, intent: Intent) -> SkillResult:
        target = max(0, min(100, intent.amount if intent.amount is not None else 50))
        self._volume.set(target)
        return SkillResult(f"Гучність {target}%.")

    def _mute(self, muted: bool) -> SkillResult:
        self._volume.set_muted(muted)
        return SkillResult("Звук вимкнено." if muted else "Звук увімкнено.")

    def _lock(self) -> SkillResult:
        self._power.lock()
        return SkillResult("Блокую, сер.")

    def _confirm_power(self, verb: str, operation: Callable[[int], None]) -> SkillResult:
        delay = self._settings.shutdown_delay_seconds

        def execute() -> SkillResult:
            operation(delay)
            return SkillResult("Виконую. До зустрічі, сер.", learnable=False)

        return SkillResult(
            f"Ви впевнені, що хочете {verb} комп'ютер?",
            confirmation=PendingConfirmation(prompt=f"{verb} комп'ютер", on_confirm=execute),
            learnable=False,
        )

    def _time(self) -> SkillResult:
        return SkillResult(f"Зараз {format_time(self._clock())}.", learnable=True)

    def _date(self) -> SkillResult:
        now = self._clock()
        return SkillResult(f"Сьогодні {WEEKDAYS[now.weekday()]}, {format_date(now.date())}.")
