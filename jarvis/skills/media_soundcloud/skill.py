from __future__ import annotations

import logging
import threading
from collections import deque

from jarvis.core.config import MusicSection
from jarvis.core.context import DialogContext, SkillResult
from jarvis.core.errors import MusicError, StorageError, TrackNotFoundError
from jarvis.core.event_bus import EventBus
from jarvis.core.events import NowPlayingChanged
from jarvis.core.intent import Intent, IntentName
from jarvis.core.models import PlayedTrack, PreferenceKind, Track
from jarvis.skills.input_control import InputController, MediaKey
from jarvis.skills.media_soundcloud.player import MusicPlayer
from jarvis.skills.media_soundcloud.recommender import MusicRecommender
from jarvis.skills.media_soundcloud.search import TrackRanker, TrackSearch
from jarvis.storage.repositories.preferences import ListeningHistoryRepository, PreferenceRepository

logger = logging.getLogger(__name__)

SESSION_HISTORY_SIZE = 20
NO_PREVIOUS_REPLY = "Попереднього треку немає, сер."


class MusicService:
    def __init__(
        self,
        search: TrackSearch,
        ranker: TrackRanker,
        player: MusicPlayer,
        recommender: MusicRecommender,
        preferences: PreferenceRepository,
        history: ListeningHistoryRepository,
        bus: EventBus,
        settings: MusicSection,
    ) -> None:
        self._search = search
        self._ranker = ranker
        self._player = player
        self._recommender = recommender
        self._preferences = preferences
        self._history = history
        self._bus = bus
        self._settings = settings
        self._lock = threading.RLock()
        self._queue: deque[Track] = deque()
        self._current: Track | None = None
        self._recommendation_mode = False
        self._hint: str | None = None
        self._started: deque[Track] = deque(maxlen=SESSION_HISTORY_SIZE)
        self._player.set_on_finished(self._on_track_finished)

    @property
    def current(self) -> Track | None:
        with self._lock:
            return self._current

    @property
    def supports_control(self) -> bool:
        return self._player.supports_control

    @property
    def is_active(self) -> bool:
        return self.supports_control and self.current is not None

    def play_query(self, query: str) -> Track:
        tracks = self._search.search(query, self._settings.search_results)
        ranked = self._ranker.rank(query, tracks)
        if not ranked:
            raise TrackNotFoundError(f"Не знайшов «{query}» на SoundCloud, сер.")
        with self._lock:
            self._recommendation_mode = False
            self._queue = deque(ranked[1:])
        return self._start(ranked[0])

    def play_recommended(self, hint: str | None) -> Track:
        suggestion = self._recommender.suggest(hint, self._recent())
        tracks = self._search.search(suggestion.query, self._settings.search_results)
        track = self._ranker.best(suggestion.query, tracks)
        with self._lock:
            self._recommendation_mode = True
            self._hint = hint
            self._queue.clear()
        return self._start(track)

    def next(self) -> Track:
        with self._lock:
            queued = self._queue.popleft() if self._queue else None
            recommend = self._recommendation_mode
            hint = self._hint
        if queued is not None:
            return self._start(queued)
        if recommend or self._current is not None:
            return self.play_recommended(hint)
        raise MusicError("Черга порожня, сер.")

    def previous(self) -> Track:
        with self._lock:
            current = self._current
            earlier = list(self._started)
            if current is not None and earlier:
                earlier.pop()
        if not earlier:
            raise MusicError(NO_PREVIOUS_REPLY)
        track = self._start(earlier[-1])
        with self._lock:
            self._started = deque(earlier, maxlen=SESSION_HISTORY_SIZE)
            if current is not None:
                self._queue.appendleft(current)
        return track

    def pause(self) -> None:
        self._player.pause()

    def resume(self) -> None:
        self._player.resume()

    def stop(self) -> None:
        self._player.stop()
        with self._lock:
            self._current = None
            self._queue.clear()
        self._bus.publish(NowPlayingChanged(None))

    def change_volume(self, delta: int) -> int:
        return self._player.change_volume(delta)

    def like_current(self) -> Track:
        track = self.current
        if track is None:
            raise MusicError("Зараз нічого не грає, сер.")
        try:
            if track.artist:
                self._preferences.bump(PreferenceKind.ARTIST, track.artist, 2.0)
            self._preferences.bump(PreferenceKind.TRACK, track.display_name, 3.0)
            self._history.mark_liked(track.url)
        except StorageError as error:
            raise MusicError("Не вдалося зберегти вподобання") from error
        return track

    def _start(self, track: Track) -> Track:
        self._player.play(track)
        with self._lock:
            self._current = track
            self._started.append(track)
        self._remember(track)
        self._bus.publish(NowPlayingChanged(track))
        logger.info("Грає: %s", track.display_name)
        return track

    def _remember(self, track: Track) -> None:
        try:
            self._history.record(track.artist, track.title, track.url)
            if track.artist:
                self._preferences.bump(PreferenceKind.ARTIST, track.artist, 0.2)
        except StorageError:
            logger.exception("Не вдалося записати історію прослуховувань")

    def _recent(self) -> list[PlayedTrack]:
        try:
            return self._history.recent(self._settings.recent_history_size)
        except StorageError:
            logger.exception("Історія прослуховувань недоступна")
            return []

    def _on_track_finished(self) -> None:
        try:
            self.next()
        except MusicError as error:
            logger.info("Автовідтворення зупинено: %s", error)
            self._mark_idle()

    def _mark_idle(self) -> None:
        with self._lock:
            self._current = None
        self._bus.publish(NowPlayingChanged(None))


class MusicSkill:
    name = "music"
    intents = frozenset(
        {
            IntentName.PLAY_MUSIC,
            IntentName.PLAY_RECOMMENDED,
            IntentName.MUSIC_PAUSE,
            IntentName.MUSIC_RESUME,
            IntentName.MUSIC_NEXT,
            IntentName.MUSIC_PREVIOUS,
            IntentName.MUSIC_STOP,
            IntentName.MUSIC_NOW_PLAYING,
            IntentName.MUSIC_LIKE,
            IntentName.MUSIC_VOLUME_UP,
            IntentName.MUSIC_VOLUME_DOWN,
        }
    )

    def __init__(self, music: MusicService, settings: MusicSection, media_keys: InputController) -> None:
        self._music = music
        self._settings = settings
        self._media_keys = media_keys

    def handle(self, intent: Intent, context: DialogContext) -> SkillResult:
        handlers = {
            IntentName.PLAY_MUSIC: self._play,
            IntentName.PLAY_RECOMMENDED: self._recommend,
            IntentName.MUSIC_PAUSE: self._pause,
            IntentName.MUSIC_RESUME: self._resume,
            IntentName.MUSIC_NEXT: self._next,
            IntentName.MUSIC_PREVIOUS: self._previous,
            IntentName.MUSIC_STOP: self._stop,
            IntentName.MUSIC_NOW_PLAYING: self._now_playing,
            IntentName.MUSIC_LIKE: self._like,
            IntentName.MUSIC_VOLUME_UP: self._louder,
            IntentName.MUSIC_VOLUME_DOWN: self._quieter,
        }
        return handlers[intent.name](intent, context)

    def _play(self, intent: Intent, context: DialogContext) -> SkillResult:
        if not intent.query:
            return self._recommend(intent, context)
        track = self._music.play_query(intent.query)
        context.remember_track(track)
        return SkillResult(f"Вмикаю {track.display_name}.")

    def _recommend(self, intent: Intent, context: DialogContext) -> SkillResult:
        track = self._music.play_recommended(intent.query)
        context.remember_track(track)
        return SkillResult(f"На мій смак — {track.display_name}.", learnable=False)

    def _pause(self, intent: Intent, context: DialogContext) -> SkillResult:
        if not self._music.is_active:
            return self._press(MediaKey.PLAY_PAUSE, "Пауза.")
        self._music.pause()
        return SkillResult("Пауза.")

    def _resume(self, intent: Intent, context: DialogContext) -> SkillResult:
        if not self._music.is_active:
            return self._press(MediaKey.PLAY_PAUSE, "Продовжую.")
        self._music.resume()
        return SkillResult("Продовжую.")

    def _next(self, intent: Intent, context: DialogContext) -> SkillResult:
        if not self._music.is_active:
            return self._press(MediaKey.NEXT, "Наступний.")
        track = self._music.next()
        context.remember_track(track)
        return SkillResult(f"Далі: {track.display_name}.")

    def _previous(self, intent: Intent, context: DialogContext) -> SkillResult:
        if not self._music.is_active:
            return self._press(MediaKey.PREVIOUS, "Попередній.")
        track = self._music.previous()
        context.remember_track(track)
        return SkillResult(f"Повертаю: {track.display_name}.")

    def _stop(self, intent: Intent, context: DialogContext) -> SkillResult:
        if not self._music.is_active:
            return self._press(MediaKey.STOP, "Зупинив.")
        self._music.stop()
        return SkillResult("Музику вимкнено.")

    def _now_playing(self, intent: Intent, context: DialogContext) -> SkillResult:
        track = self._music.current
        if track is None:
            return SkillResult("У моєму плеєрі зараз нічого не грає, сер.")
        return SkillResult(f"Зараз грає {track.display_name}.")

    def _like(self, intent: Intent, context: DialogContext) -> SkillResult:
        track = self._music.like_current()
        return SkillResult(f"Запам'ятав, вам подобається {track.display_name}.")

    def _louder(self, intent: Intent, context: DialogContext) -> SkillResult:
        volume = self._music.change_volume(intent.amount or self._settings.volume_step)
        return SkillResult(f"Гучність плеєра {volume}%.")

    def _quieter(self, intent: Intent, context: DialogContext) -> SkillResult:
        volume = self._music.change_volume(-(intent.amount or self._settings.volume_step))
        return SkillResult(f"Гучність плеєра {volume}%.")

    def _press(self, key: MediaKey, reply: str) -> SkillResult:
        self._media_keys.press_media(key)
        return SkillResult(reply)
