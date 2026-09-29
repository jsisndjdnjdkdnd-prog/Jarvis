from __future__ import annotations

import logging
import random
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from jarvis.core.errors import DeepSeekError
from jarvis.core.models import PlayedTrack, Preference, PreferenceKind
from jarvis.nlu.deepseek_client import DeepSeekClient
from jarvis.storage.repositories.preferences import PreferenceRepository

logger = logging.getLogger(__name__)

MUSIC_PURPOSE = "music"

DEFAULT_ARTISTS_BY_PERIOD: dict[str, tuple[str, ...]] = {
    "morning": ("Coldplay", "The Weeknd", "Океан Ельзи", "Imagine Dragons", "Dua Lipa"),
    "day": ("Daft Punk", "Arctic Monkeys", "Бумбокс", "Linkin Park", "Calvin Harris"),
    "evening": ("Lana Del Rey", "Hozier", "The Neighbourhood", "Kalush", "Tame Impala"),
    "night": ("Bonobo", "Massive Attack", "Moby", "Hans Zimmer", "Ludovico Einaudi"),
}


class TrackSuggestion(BaseModel):
    model_config = ConfigDict(extra="ignore")

    artist: str = Field(min_length=1)
    title: str = ""

    @property
    def query(self) -> str:
        return f"{self.artist} {self.title}".strip()


class MusicRecommender(Protocol):
    def suggest(self, hint: str | None, recent: Sequence[PlayedTrack]) -> TrackSuggestion: ...


def day_period(moment: datetime) -> str:
    if 5 <= moment.hour < 12:
        return "morning"
    if 12 <= moment.hour < 18:
        return "day"
    if 18 <= moment.hour < 23:
        return "evening"
    return "night"


class DeepSeekMusicRecommender:
    def __init__(
        self,
        client: DeepSeekClient,
        preferences: PreferenceRepository,
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._client = client
        self._preferences = preferences
        self._clock = clock

    @property
    def available(self) -> bool:
        return self._client.available

    def suggest(self, hint: str | None, recent: Sequence[PlayedTrack]) -> TrackSuggestion:
        suggestion = self._client.complete_json(
            system_prompt=self._system_prompt(),
            user_prompt=self._user_prompt(hint, recent),
            purpose=MUSIC_PURPOSE,
            parse=self._parse,
        )
        if self._is_recent(suggestion, recent):
            raise DeepSeekError("DeepSeek запропонував нещодавній трек")
        return suggestion

    @staticmethod
    def _parse(data: dict[str, Any]) -> TrackSuggestion:
        suggestion = TrackSuggestion.model_validate(data)
        if not suggestion.title.strip():
            raise ValueError("title is required")
        return suggestion

    @staticmethod
    def _system_prompt() -> str:
        return (
            "You are a music curator for a voice assistant. Pick exactly ONE real, existing track "
            "that is very likely available on SoundCloud. Respect user taste, mood hint and time of day. "
            "Never pick tracks from the recent list. Answer with json only: "
            '{"artist": "<artist>", "title": "<track title>"}'
        )

    def _user_prompt(self, hint: str | None, recent: Sequence[PlayedTrack]) -> str:
        now = self._clock()
        artists = self._describe(self._preferences.top(PreferenceKind.ARTIST, 10))
        genres = self._describe(self._preferences.top(PreferenceKind.GENRE, 5))
        liked = self._describe(self._preferences.top(PreferenceKind.TRACK, 10))
        recent_list = "; ".join(f"{item.artist} - {item.title}" for item in recent) or "none"
        return (
            f"Local time: {now.strftime('%H:%M')} ({day_period(now)}), weekday {now.strftime('%A')}.\n"
            f"Mood/genre hint from user: {hint or 'none'}.\n"
            f"Favourite artists: {artists}.\nFavourite genres: {genres}.\nLiked tracks: {liked}.\n"
            f"Recently played (do not repeat): {recent_list}."
        )

    @staticmethod
    def _describe(preferences: Sequence[Preference]) -> str:
        return ", ".join(preference.value for preference in preferences) or "unknown"

    @staticmethod
    def _is_recent(suggestion: TrackSuggestion, recent: Sequence[PlayedTrack]) -> bool:
        title = suggestion.title.lower()
        artist = suggestion.artist.lower()
        return any(item.title.lower() == title and item.artist.lower() == artist for item in recent)


class LocalMusicRecommender:
    def __init__(
        self,
        preferences: PreferenceRepository,
        clock: Callable[[], datetime] = datetime.now,
        rng: random.Random | None = None,
    ) -> None:
        self._preferences = preferences
        self._clock = clock
        self._rng = rng or random.Random()

    def suggest(self, hint: str | None, recent: Sequence[PlayedTrack]) -> TrackSuggestion:
        recent_artists = {item.artist.lower() for item in recent[:3]}
        favourites = [pref.value for pref in self._preferences.top(PreferenceKind.ARTIST, 15)]
        pool = [artist for artist in favourites if artist.lower() not in recent_artists]
        if not pool:
            pool = list(DEFAULT_ARTISTS_BY_PERIOD[day_period(self._clock())])
        artist = self._rng.choice(pool)
        return TrackSuggestion(artist=artist, title=hint or "")


class FallbackMusicRecommender:
    def __init__(self, primary: DeepSeekMusicRecommender, fallback: MusicRecommender) -> None:
        self._primary = primary
        self._fallback = fallback

    def suggest(self, hint: str | None, recent: Sequence[PlayedTrack]) -> TrackSuggestion:
        if self._primary.available:
            try:
                return self._primary.suggest(hint, recent)
            except DeepSeekError as error:
                logger.warning("DeepSeek не зміг підібрати трек: %s", error)
        return self._fallback.suggest(hint, recent)
