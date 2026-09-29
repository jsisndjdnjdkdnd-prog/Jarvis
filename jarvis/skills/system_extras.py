from __future__ import annotations

import logging
from typing import Protocol

from jarvis.core.context import DialogContext, PendingConfirmation, SkillResult
from jarvis.core.errors import ActionExecutionError, SkillError
from jarvis.core.event_bus import EventBus
from jarvis.core.events import ListeningModeChanged
from jarvis.core.intent import Intent, IntentName
from jarvis.skills.platform import ShellOpener, require_windows
from jarvis.skills.system import VolumeController

logger = logging.getLogger(__name__)

SETTINGS_URIS: dict[str, str] = {
    "bluetooth": "ms-settings:bluetooth",
    "wifi": "ms-settings:network-wifi",
    "network": "ms-settings:network-status",
    "sound": "ms-settings:sound",
    "display": "ms-settings:display",
    "updates": "ms-settings:windowsupdate",
    "apps": "ms-settings:appsfeatures",
    "privacy": "ms-settings:privacy",
    "mouse": "ms-settings:mousetouchpad",
    "keyboard": "ms-settings:easeofaccess-keyboard",
    "language": "ms-settings:regionlanguage",
    "notifications": "ms-settings:notifications",
    "power": "ms-settings:powersleep",
    "personalization": "ms-settings:personalization",
    "storage": "ms-settings:storagesense",
}

SETTINGS_NAMES: dict[str, str] = {
    "bluetooth": "Bluetooth",
    "wifi": "Wi-Fi",
    "network": "мережі",
    "sound": "звуку",
    "display": "екрана",
    "updates": "оновлень",
    "apps": "програм",
    "privacy": "конфіденційності",
    "mouse": "миші",
    "keyboard": "клавіатури",
    "language": "мови",
    "notifications": "сповіщень",
    "power": "живлення",
    "personalization": "персоналізації",
    "storage": "пам'яті",
}


class PowerExtras(Protocol):
    def sleep(self) -> None: ...

    def empty_recycle_bin(self) -> None: ...


class WindowsPowerExtras:
    def sleep(self) -> None:
        require_windows("Режим сну")
        import ctypes

        try:
            ctypes.windll.powrprof.SetSuspendState(0, 1, 0)
        except OSError as error:
            raise ActionExecutionError("Не вдалося перевести комп'ютер у сон, сер.") from error

    def empty_recycle_bin(self) -> None:
        require_windows("Очищення кошика")
        import ctypes

        flags = 0x1 | 0x2 | 0x4
        try:
            ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, flags)
        except OSError as error:
            raise ActionExecutionError("Не вдалося очистити кошик, сер.") from error


class SystemExtrasSkill:
    name = "system_extras"
    intents = frozenset(
        {
            IntentName.VOLUME_GET,
            IntentName.SLEEP_PC,
            IntentName.EMPTY_RECYCLE_BIN,
            IntentName.OPEN_SETTINGS,
            IntentName.LISTEN_MODE,
        }
    )

    def __init__(
        self,
        bus: EventBus,
        volume: VolumeController,
        power: PowerExtras,
        opener: ShellOpener,
    ) -> None:
        self._bus = bus
        self._volume = volume
        self._power = power
        self._opener = opener

    def handle(self, intent: Intent, context: DialogContext) -> SkillResult:
        if intent.name is IntentName.VOLUME_GET:
            return self._volume_get()
        if intent.name is IntentName.SLEEP_PC:
            return self._sleep()
        if intent.name is IntentName.EMPTY_RECYCLE_BIN:
            return self._empty_recycle_bin()
        if intent.name is IntentName.OPEN_SETTINGS:
            return self._open_settings(intent)
        return self._listen_mode(intent)

    def _volume_get(self) -> SkillResult:
        return SkillResult(f"Гучність зараз {self._volume.get()}%.")

    def _sleep(self) -> SkillResult:
        self._power.sleep()
        return SkillResult("Переходжу в режим сну, сер.", learnable=False, speak=True)

    def _empty_recycle_bin(self) -> SkillResult:
        def execute() -> SkillResult:
            self._power.empty_recycle_bin()
            return SkillResult("Кошик очищено, сер.")

        return SkillResult(
            "Очистити кошик остаточно?",
            confirmation=PendingConfirmation(prompt="очистити кошик", on_confirm=execute),
            learnable=False,
        )

    def _open_settings(self, intent: Intent) -> SkillResult:
        page = intent.target or ""
        uri = SETTINGS_URIS.get(page)
        if uri is None:
            self._opener.open("ms-settings:")
            return SkillResult("Відкриваю налаштування Windows.")
        try:
            self._opener.open(uri)
        except ActionExecutionError as error:
            raise SkillError("Не вдалося відкрити налаштування, сер.") from error
        return SkillResult(f"Відкриваю налаштування {SETTINGS_NAMES.get(page, page)}.")

    def _listen_mode(self, intent: Intent) -> SkillResult:
        always = intent.mode == "always"
        self._bus.publish(ListeningModeChanged(always_listen=always))
        if always:
            return SkillResult("Гаразд, слухаю постійно, сер. Скажіть «слухай лише на ім'я», щоб вимкнути.", learnable=False)
        return SkillResult("Повертаюсь до режиму на ім'я, сер.", learnable=False)
