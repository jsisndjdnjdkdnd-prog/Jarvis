from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote_plus

from jarvis.core.context import DialogContext, SkillResult
from jarvis.core.errors import ActionExecutionError, MusicError
from jarvis.core.intent import Intent, IntentName
from jarvis.skills.web_search import UrlOpener

logger = logging.getLogger(__name__)

YOUTUBE_HOME_URL = "https://www.youtube.com"
YOUTUBE_WATCH_URL = "https://www.youtube.com/watch?v="
YOUTUBE_RESULTS_URL = "https://www.youtube.com/results?search_query="
WATCH_URL_PREFIXES: tuple[str, ...] = (
    "https://www.youtube.com/watch?",
    "https://youtube.com/watch?",
    "https://m.youtube.com/watch?",
    "http://www.youtube.com/watch?",
)
DEFAULT_RESULT_LIMIT = 5
MAX_SPOKEN_TITLE_LENGTH = 80


@dataclass(frozen=True)
class VideoResult:
    title: str
    url: str
    channel: str
    duration_seconds: float | None


class YouTubeSearch(Protocol):
    def search(self, query: str, limit: int) -> list[VideoResult]: ...


class MediaInfoExtractor(Protocol):
    def extract(self, target: str, full: bool) -> dict[str, Any]: ...


class YtDlpYouTubeSearch:
    def __init__(self, client: MediaInfoExtractor) -> None:
        self._client = client

    def search(self, query: str, limit: int) -> list[VideoResult]:
        try:
            info = self._client.extract(f"ytsearch{max(1, limit)}:{query}", full=False)
        except ImportError as error:
            raise MusicError("yt-dlp не встановлено") from error
        entries = info.get("entries") or []
        return [video for video in (self._to_video(entry) for entry in entries) if video is not None]

    @classmethod
    def _to_video(cls, entry: dict[str, Any] | None) -> VideoResult | None:
        if not entry:
            return None
        url = cls._watch_url(entry)
        if url is None:
            return None
        duration = entry.get("duration")
        return VideoResult(
            title=str(entry.get("title") or "").strip(),
            url=url,
            channel=str(entry.get("channel") or entry.get("uploader") or "").strip(),
            duration_seconds=float(duration) if isinstance(duration, int | float) else None,
        )

    @staticmethod
    def _watch_url(entry: dict[str, Any]) -> str | None:
        for key in ("url", "webpage_url", "original_url"):
            candidate = str(entry.get(key) or "")
            if candidate.startswith(WATCH_URL_PREFIXES) and "v=" in candidate:
                return candidate
        video_id = str(entry.get("id") or "").strip()
        if not video_id:
            return None
        return f"{YOUTUBE_WATCH_URL}{video_id}"


class YouTubePlaySkill:
    name = "youtube"
    intents = frozenset({IntentName.YOUTUBE_PLAY})

    def __init__(self, search: YouTubeSearch, opener: UrlOpener, limit: int = DEFAULT_RESULT_LIMIT) -> None:
        self._search = search
        self._opener = opener
        self._limit = limit

    def handle(self, intent: Intent, context: DialogContext) -> SkillResult:
        query = (intent.query or intent.target or "").strip()
        if not query:
            return self._open(YOUTUBE_HOME_URL, "Відкриваю YouTube.")
        video = self._best_video(query)
        if video is None:
            return self._open(f"{YOUTUBE_RESULTS_URL}{quote_plus(query)}", "Відкрив пошук на YouTube.")
        return self._open(video.url, f"Вмикаю «{self._spoken_title(video, query)}» на YouTube.")

    def _best_video(self, query: str) -> VideoResult | None:
        try:
            results = self._search.search(query, self._limit)
        except MusicError as error:
            logger.warning("Пошук на YouTube не вдався: %s", error)
            return None
        return next((video for video in results if video.url), None)

    def _open(self, url: str, reply: str) -> SkillResult:
        try:
            self._opener.open(url)
        except ActionExecutionError as error:
            logger.warning("Не вдалося відкрити %s: %s", url, error)
            return SkillResult("Не вдалося відкрити браузер, сер.", success=False, learnable=False)
        return SkillResult(reply, learnable=False)

    @staticmethod
    def _spoken_title(video: VideoResult, query: str) -> str:
        title = " ".join(video.title.split()) or query
        if len(title) <= MAX_SPOKEN_TITLE_LENGTH:
            return title
        shortened = title[:MAX_SPOKEN_TITLE_LENGTH].rsplit(" ", 1)[0]
        return shortened.rstrip(" -|,.:;") + "…"
