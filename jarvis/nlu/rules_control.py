from __future__ import annotations

from jarvis.core.intent import Intent, IntentName, WindowCommand, YouTubeCommand
from jarvis.nlu import lexicon as lx
from jarvis.nlu import lexicon_ext as lxe
from jarvis.nlu.durations import DurationParser
from jarvis.nlu.prepared_text import PreparedText, Rule

DEFAULT_SEEK_SECONDS = 10
MAX_TYPED_TOKENS = 60


class ControlRules:
    def __init__(self, durations: DurationParser) -> None:
        self._durations = durations

    def rules(self) -> tuple[Rule, ...]:
        return (
            self.power_extras,
            self.volume_extras,
            self.youtube_control,
            self.youtube_play,
            self.web_search,
            self.open_settings,
            self.type_text,
            self.window_control,
            self.previous_track,
        )

    def power_extras(self, prepared: PreparedText) -> Intent | None:
        if prepared.contains(lxe.RECYCLE_BIN_PHRASES):
            return Intent(name=IntentName.EMPTY_RECYCLE_BIN)
        if prepared.contains(lxe.SLEEP_PHRASES):
            return Intent(name=IntentName.SLEEP_PC)
        return None

    def volume_extras(self, prepared: PreparedText) -> Intent | None:
        if prepared.contains(lxe.VOLUME_GET_PHRASES):
            return Intent(name=IntentName.VOLUME_GET)
        if not prepared.has_stem(lxe.VOLUME_CONTEXT_WORDS) or prepared.has_stem(lx.MUSIC_STEMS):
            return None
        if prepared.has_stem(lxe.VOLUME_MAX_WORDS):
            return Intent(name=IntentName.VOLUME_SET, amount=100)
        if prepared.has_stem(lxe.VOLUME_MIN_WORDS):
            return Intent(name=IntentName.VOLUME_SET, amount=10)
        if prepared.has_stem(lxe.VOLUME_HALF_WORDS):
            return Intent(name=IntentName.VOLUME_SET, amount=50)
        amount = prepared.first_number()
        if amount is not None and not prepared.contains(lx.VOLUME_UP_PHRASES + lx.VOLUME_DOWN_PHRASES):
            return Intent(name=IntentName.VOLUME_SET, amount=min(amount, 100))
        return None

    def youtube_control(self, prepared: PreparedText) -> Intent | None:
        about_video = prepared.has_token(lxe.YOUTUBE_WORDS) or prepared.has_token(lxe.VIDEO_WORDS)
        for stems, command in lxe.YOUTUBE_CONTROL_TRIGGERS:
            if prepared.has_stem(stems):
                return Intent(name=IntentName.YOUTUBE_CONTROL, mode=command.value)
        if prepared.has_stem(lxe.REWIND_STEMS):
            return self._seek(prepared)
        if not about_video:
            return None
        return self._video_command(prepared)

    def _seek(self, prepared: PreparedText) -> Intent:
        backward = prepared.has_stem(lxe.YOUTUBE_BACKWARD_STEMS)
        found = self._durations.find(prepared.tokens)
        seconds = found[0] if found is not None else DEFAULT_SEEK_SECONDS
        command = YouTubeCommand.BACKWARD if backward else YouTubeCommand.FORWARD
        return Intent(name=IntentName.YOUTUBE_CONTROL, mode=command.value, amount=seconds)

    def _video_command(self, prepared: PreparedText) -> Intent | None:
        checks: tuple[tuple[bool, YouTubeCommand], ...] = (
            (prepared.contains(lxe.FULLSCREEN_PHRASES), YouTubeCommand.FULLSCREEN),
            (prepared.has_stem(("наступн", "следующ", "next")), YouTubeCommand.NEXT),
            (prepared.has_stem(("попередн", "предыдущ", "previous")), YouTubeCommand.PREVIOUS),
            (prepared.has_stem(lxe.FASTER_STEMS), YouTubeCommand.FASTER),
            (prepared.has_stem(lxe.SLOWER_STEMS), YouTubeCommand.SLOWER),
            (prepared.contains(lx.MUTE_PHRASES) or prepared.has_stem(("заглуш",)), YouTubeCommand.MUTE),
            (prepared.has_stem(("пауз", "зупини", "призупин", "останов", "pause")), YouTubeCommand.PAUSE),
            (prepared.has_stem(("продовж", "віднов", "продолж", "resume")), YouTubeCommand.PLAY),
        )
        for matched, command in checks:
            if matched:
                return Intent(name=IntentName.YOUTUBE_CONTROL, mode=command.value)
        return None

    def youtube_play(self, prepared: PreparedText) -> Intent | None:
        mentions_youtube = prepared.has_token(lxe.YOUTUBE_WORDS)
        mentions_video = prepared.has_token(lxe.VIDEO_WORDS)
        if prepared.head not in lxe.YOUTUBE_PLAY_VERBS or not (mentions_youtube or mentions_video):
            return None
        query_tokens = [
            token
            for token in prepared.tail
            if token not in lxe.YOUTUBE_WORDS and token not in lxe.VIDEO_WORDS
        ]
        while query_tokens and query_tokens[0] in lxe.YOUTUBE_QUERY_FILLERS:
            query_tokens.pop(0)
        while query_tokens and query_tokens[-1] in lxe.YOUTUBE_QUERY_FILLERS:
            query_tokens.pop()
        query = " ".join(query_tokens)
        return Intent(name=IntentName.YOUTUBE_PLAY, query=query or None)

    def web_search(self, prepared: PreparedText) -> Intent | None:
        for prefix in lxe.WEB_SEARCH_PREFIXES:
            if prepared.core.startswith(prefix + " "):
                query = prepared.core[len(prefix) :].strip()
                return Intent(name=IntentName.WEB_SEARCH, query=query) if query else None
        return None

    def open_settings(self, prepared: PreparedText) -> Intent | None:
        if prepared.head not in lx.OPEN_VERBS or not prepared.has_token(lxe.SETTINGS_WORDS):
            return None
        for page, words in lxe.SETTINGS_PAGES.items():
            if prepared.contains(words):
                return Intent(name=IntentName.OPEN_SETTINGS, target=page)
        return None

    def type_text(self, prepared: PreparedText) -> Intent | None:
        if prepared.head not in lxe.TYPE_TEXT_VERBS or len(prepared.tokens) < 2:
            return None
        if len(prepared.tokens) > MAX_TYPED_TOKENS:
            return None
        return Intent(name=IntentName.TYPE_TEXT, message=" ".join(prepared.tail))

    def window_control(self, prepared: PreparedText) -> Intent | None:
        for phrases, command in lxe.WINDOW_PHRASES:
            if prepared.equals(phrases) or prepared.contains(phrase for phrase in phrases if " " in phrase):
                return Intent(name=IntentName.WINDOW_CONTROL, mode=command.value, amount=self._repeats(prepared, command))
        return None

    @staticmethod
    def _repeats(prepared: PreparedText, command: WindowCommand) -> int | None:
        repeatable = {WindowCommand.SCROLL_DOWN, WindowCommand.SCROLL_UP, WindowCommand.ZOOM_IN, WindowCommand.ZOOM_OUT}
        if command not in repeatable:
            return None
        return prepared.first_number()

    def previous_track(self, prepared: PreparedText) -> Intent | None:
        if prepared.equals(lxe.PREVIOUS_TRACK_PHRASES) or prepared.contains(
            phrase for phrase in lxe.PREVIOUS_TRACK_PHRASES if " " in phrase
        ):
            return Intent(name=IntentName.MUSIC_PREVIOUS)
        return None
