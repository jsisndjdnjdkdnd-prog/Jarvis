from __future__ import annotations

import logging
import threading
import webbrowser
from collections.abc import Callable
from typing import Any, Protocol

from jarvis.core.errors import MusicError
from jarvis.core.models import Track
from jarvis.skills.media_soundcloud.search import StreamResolver

logger = logging.getLogger(__name__)

FinishedCallback = Callable[[], None]


class MusicPlayer(Protocol):
    @property
    def supports_control(self) -> bool: ...

    def play(self, track: Track) -> None: ...

    def pause(self) -> None: ...

    def resume(self) -> None: ...

    def stop(self) -> None: ...

    def change_volume(self, delta: int) -> int: ...

    def set_on_finished(self, callback: FinishedCallback) -> None: ...


class VlcPlayer:
    def __init__(self, resolver: StreamResolver, initial_volume: int) -> None:
        self._resolver = resolver
        self._volume = initial_volume
        self._lock = threading.RLock()
        self._instance: Any = None
        self._player: Any = None
        self._on_finished: FinishedCallback | None = None

    @property
    def supports_control(self) -> bool:
        return True

    def set_on_finished(self, callback: FinishedCallback) -> None:
        self._on_finished = callback

    def play(self, track: Track) -> None:
        stream = track.stream_url or self._resolver.resolve(track.url)
        with self._lock:
            player = self._ensure_player()
            media = self._instance.media_new(stream)
            player.set_media(media)
            if player.play() == -1:
                raise MusicError("VLC не зміг відтворити трек")
            player.audio_set_volume(self._volume)

    def pause(self) -> None:
        with self._lock:
            if self._player is not None:
                self._player.set_pause(1)

    def resume(self) -> None:
        with self._lock:
            if self._player is not None:
                self._player.set_pause(0)

    def stop(self) -> None:
        with self._lock:
            if self._player is not None:
                self._player.stop()

    def change_volume(self, delta: int) -> int:
        with self._lock:
            self._volume = max(0, min(100, self._volume + delta))
            if self._player is not None:
                self._player.audio_set_volume(self._volume)
            return self._volume

    def _ensure_player(self) -> Any:
        if self._player is not None:
            return self._player
        try:
            import vlc
        except (ImportError, OSError) as error:
            raise MusicError("VLC не встановлено. Встановіть VLC або виберіть backend: browser") from error
        self._instance = vlc.Instance("--no-video", "--quiet")
        if self._instance is None:
            raise MusicError("Не вдалося ініціалізувати VLC")
        self._player = self._instance.media_player_new()
        events = self._player.event_manager()
        events.event_attach(vlc.EventType.MediaPlayerEndReached, self._handle_end)
        return self._player

    def _handle_end(self, event: Any) -> None:
        callback = self._on_finished
        if callback is not None:
            threading.Thread(target=callback, name="music-next", daemon=True).start()


class BrowserPlayer:
    @property
    def supports_control(self) -> bool:
        return False

    def set_on_finished(self, callback: FinishedCallback) -> None:
        return None

    def play(self, track: Track) -> None:
        if not webbrowser.open(track.url):
            raise MusicError("Не вдалося відкрити браузер")

    def pause(self) -> None:
        raise MusicError("У режимі браузера керувати відтворенням я не можу, сер.")

    def resume(self) -> None:
        self.pause()

    def stop(self) -> None:
        self.pause()

    def change_volume(self, delta: int) -> int:
        raise MusicError("У режимі браузера гучність плеєра недоступна, сер.")
