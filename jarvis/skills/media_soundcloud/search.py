from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from typing import Any, Protocol

import httpx
from rapidfuzz import fuzz

from jarvis.core.errors import MusicError, TrackNotFoundError
from jarvis.core.models import Track
from jarvis.nlu.transliteration import contains_cyrillic, cyrillic_to_latin

logger = logging.getLogger(__name__)

API_SEARCH_URL = "https://api-v2.soundcloud.com/search/tracks"
PREVIEW_MAX_SECONDS = 35
VARIANT_MARKERS: tuple[str, ...] = ("remix", "cover", "nightcore", "sped up", "slowed", "8d", "karaoke", "instrumental", "reverb")
_SPACES = re.compile(r"\s+")


class TrackSearch(Protocol):
    def search(self, query: str, limit: int) -> list[Track]: ...


class StreamResolver(Protocol):
    def resolve(self, page_url: str) -> str: ...


class YtDlpClient:
    def extract(self, target: str, full: bool) -> dict[str, Any]:
        from yt_dlp import YoutubeDL
        from yt_dlp.utils import DownloadError

        options: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "noplaylist": True,
            "format": "bestaudio/best",
        }
        if not full:
            options["extract_flat"] = "in_playlist"
        try:
            with YoutubeDL(options) as downloader:
                info = downloader.extract_info(target, download=False)
        except DownloadError as error:
            raise MusicError(f"SoundCloud недоступний: {error}") from error
        return info or {}


class YtDlpSoundCloudSearch:
    def __init__(self, client: YtDlpClient) -> None:
        self._client = client

    def search(self, query: str, limit: int) -> list[Track]:
        info = self._client.extract(f"scsearch{limit}:{query}", full=True)
        return [track for track in (self._to_track(entry) for entry in info.get("entries") or []) if track]

    @staticmethod
    def _to_track(entry: dict[str, Any] | None) -> Track | None:
        if not entry:
            return None
        url = entry.get("webpage_url") or entry.get("original_url") or entry.get("url")
        if not url:
            return None
        return Track(
            title=str(entry.get("track") or entry.get("title") or ""),
            artist=str(entry.get("artist") or entry.get("uploader") or ""),
            url=str(url),
            duration_seconds=entry.get("duration"),
            source_id=str(entry.get("id") or ""),
            stream_url=entry.get("url") if entry.get("url") != url else None,
        )


class SoundCloudApiSearch:
    def __init__(self, client_id: str, timeout: float = 10.0) -> None:
        self._client_id = client_id
        self._timeout = timeout

    def search(self, query: str, limit: int) -> list[Track]:
        try:
            response = httpx.get(
                API_SEARCH_URL,
                params={"q": query, "client_id": self._client_id, "limit": limit},
                timeout=self._timeout,
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise MusicError(f"SoundCloud API: {error}") from error
        collection = response.json().get("collection", [])
        return [self._to_track(item) for item in collection if item.get("permalink_url")]

    @staticmethod
    def _to_track(item: dict[str, Any]) -> Track:
        duration_ms = item.get("full_duration") or item.get("duration")
        return Track(
            title=str(item.get("title", "")),
            artist=str((item.get("user") or {}).get("username", "")),
            url=str(item["permalink_url"]),
            duration_seconds=duration_ms / 1000 if duration_ms else None,
            source_id=str(item.get("id", "")),
        )


class FallbackTrackSearch:
    def __init__(self, primary: TrackSearch, fallback: TrackSearch | None) -> None:
        self._primary = primary
        self._fallback = fallback

    def search(self, query: str, limit: int) -> list[Track]:
        try:
            results = self._primary.search(query, limit)
        except MusicError as error:
            if self._fallback is None:
                raise
            logger.warning("Основний пошук SoundCloud не спрацював: %s", error)
            return self._fallback.search(query, limit)
        if results or self._fallback is None:
            return results
        return self._fallback.search(query, limit)


class YtDlpStreamResolver:
    def __init__(self, client: YtDlpClient) -> None:
        self._client = client

    def resolve(self, page_url: str) -> str:
        info = self._client.extract(page_url, full=True)
        stream = info.get("url")
        if not stream:
            raise MusicError("Не вдалося отримати аудіопотік")
        return str(stream)


class TrackRanker:
    def rank(self, query: str, tracks: Sequence[Track]) -> list[Track]:
        return sorted(tracks, key=lambda track: self.score(query, track), reverse=True)

    def best(self, query: str, tracks: Sequence[Track]) -> Track:
        ranked = self.rank(query, tracks)
        if not ranked:
            raise TrackNotFoundError(f"Не знайшов «{query}» на SoundCloud, сер.")
        return ranked[0]

    def score(self, query: str, track: Track) -> float:
        normalized_query = self._comparable(query)
        haystack = self._comparable(f"{track.artist} {track.title}")
        score = float(fuzz.token_set_ratio(normalized_query, haystack))
        if track.duration_seconds is not None and track.duration_seconds <= PREVIEW_MAX_SECONDS:
            score -= 40
        elif track.duration_seconds is not None:
            score += 8
        for marker in VARIANT_MARKERS:
            if marker in haystack and marker not in normalized_query:
                score -= 12
        return score

    @staticmethod
    def _comparable(text: str) -> str:
        lowered = _SPACES.sub(" ", text.lower()).strip()
        return cyrillic_to_latin(lowered) if contains_cyrillic(lowered) else lowered
