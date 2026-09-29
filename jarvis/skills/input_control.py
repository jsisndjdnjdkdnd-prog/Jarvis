from __future__ import annotations

import logging
from enum import StrEnum
from types import ModuleType
from typing import Protocol

from jarvis.core.errors import ActionExecutionError
from jarvis.skills.platform import require_windows

logger = logging.getLogger(__name__)

KEYEVENTF_EXTENDEDKEY = 0x1
KEYEVENTF_KEYUP = 0x2

KeyboardKey = str | int


class MediaKey(StrEnum):
    PLAY_PAUSE = "play_pause"
    NEXT = "next"
    PREVIOUS = "previous"
    STOP = "stop"
    VOLUME_MUTE = "volume_mute"


MEDIA_VIRTUAL_KEYS: dict[MediaKey, int] = {
    MediaKey.PLAY_PAUSE: 0xB3,
    MediaKey.NEXT: 0xB0,
    MediaKey.PREVIOUS: 0xB1,
    MediaKey.STOP: 0xB2,
    MediaKey.VOLUME_MUTE: 0xAD,
}

LAYOUT_INDEPENDENT_KEYS: dict[str, int] = {
    "plus": 0xBB,
    "minus": 0xBD,
    "comma": 0xBC,
    "period": 0xBE,
}


class InputController(Protocol):
    def press_media(self, key: MediaKey) -> None: ...

    def send(self, combination: str) -> None: ...

    def write(self, text: str) -> None: ...


def keyboard_keys(combination: str) -> list[KeyboardKey]:
    names = [part.strip().lower() for part in combination.split("+")]
    if any(not name for name in names):
        raise ActionExecutionError(f"Невідома комбінація клавіш «{combination}», сер.")
    return [_keyboard_key(name) for name in names]


def _keyboard_key(name: str) -> KeyboardKey:
    virtual_key = LAYOUT_INDEPENDENT_KEYS.get(name)
    if virtual_key is None:
        return name
    return -virtual_key


class WindowsInputController:
    def press_media(self, key: MediaKey) -> None:
        require_windows("Керування медіа")
        import ctypes

        virtual_key = MEDIA_VIRTUAL_KEYS[key]
        try:
            user32 = ctypes.windll.user32
            user32.keybd_event(virtual_key, 0, KEYEVENTF_EXTENDEDKEY, 0)
            user32.keybd_event(virtual_key, 0, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP, 0)
        except OSError as error:
            raise ActionExecutionError("Не вдалося натиснути медіаклавішу, сер.") from error
        logger.debug("Натиснуто медіаклавішу %s", key.value)

    def send(self, combination: str) -> None:
        require_windows("Натискання клавіш")
        keys = keyboard_keys(combination)
        keyboard = self._keyboard()
        try:
            keyboard.send(keys)
        except ValueError as error:
            raise ActionExecutionError(f"Невідома комбінація клавіш «{combination}», сер.") from error
        except OSError as error:
            raise ActionExecutionError("Клавіатура зараз недоступна, сер.") from error
        logger.debug("Надіслано комбінацію %s", combination)

    def write(self, text: str) -> None:
        require_windows("Введення тексту")
        keyboard = self._keyboard()
        try:
            keyboard.write(text)
        except (ValueError, OSError) as error:
            raise ActionExecutionError("Не вдалося надрукувати текст, сер.") from error

    @staticmethod
    def _keyboard() -> ModuleType:
        try:
            import keyboard
        except ImportError as error:
            raise ActionExecutionError("Бібліотека keyboard не встановлена, сер.") from error
        return keyboard
