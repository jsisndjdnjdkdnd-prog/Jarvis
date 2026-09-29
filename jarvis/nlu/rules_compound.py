from __future__ import annotations

import re
from collections.abc import Callable

from jarvis.core.intent import Action, ActionType, Intent, IntentName
from jarvis.nlu import lexicon as lx
from jarvis.nlu.intent_actions import IntentActionMapper
from jarvis.nlu.prepared_text import PreparedText

CHAINABLE: frozenset[IntentName] = frozenset(
    {
        IntentName.OPEN_APP,
        IntentName.CLOSE_APP,
        IntentName.OPEN_FOLDER,
        IntentName.OPEN_URL,
        IntentName.OPEN_SETTINGS,
        IntentName.RESCAN_PROGRAMS,
        IntentName.PLAY_MUSIC,
        IntentName.PLAY_RECOMMENDED,
        IntentName.MUSIC_PAUSE,
        IntentName.MUSIC_RESUME,
        IntentName.MUSIC_NEXT,
        IntentName.MUSIC_PREVIOUS,
        IntentName.MUSIC_STOP,
        IntentName.MUSIC_VOLUME_UP,
        IntentName.MUSIC_VOLUME_DOWN,
        IntentName.YOUTUBE_PLAY,
        IntentName.YOUTUBE_CONTROL,
        IntentName.WEB_SEARCH,
        IntentName.VOLUME_UP,
        IntentName.VOLUME_DOWN,
        IntentName.VOLUME_SET,
        IntentName.MUTE,
        IntentName.UNMUTE,
        IntentName.SCREENSHOT,
        IntentName.TIMER_SET,
        IntentName.WINDOW_CONTROL,
        IntentName.TYPE_TEXT,
        IntentName.LOCK_PC,
        IntentName.SLEEP_PC,
        IntentName.EMPTY_RECYCLE_BIN,
        IntentName.WEATHER,
        IntentName.SYSTEM_INFO,
        IntentName.TIME_NOW,
        IntentName.DATE_NOW,
    }
)

_SPLIT = re.compile(
    r"\s+(?:а потім|і потім|та потім|потім|після цього|а тоді|затем|потом|and then|then|,)\s+|\s*,\s*"
)
_SOFT_SPLIT = re.compile(r"\s+(?:і|та|й|и|and)\s+")
MAX_STEPS = 6


class CompoundRule:
    def __init__(self, parse: Callable[[str], Intent | None], mapper: IntentActionMapper) -> None:
        self._parse = parse
        self._mapper = mapper

    def compound(self, prepared: PreparedText) -> Intent | None:
        if prepared.head in lx.LEARN_VERBS:
            return None
        segments = self._segments(prepared.core)
        if len(segments) < 2:
            return None
        actions = self._resolve(segments)
        if actions is None or len(actions) < 2:
            return None
        return Intent(name=IntentName.RUN_PLAN, actions=tuple(actions))

    def _segments(self, text: str) -> list[str]:
        parts = [part.strip() for part in _SPLIT.split(text) if part.strip()]
        if len(parts) > 1:
            return parts
        return [part.strip() for part in _SOFT_SPLIT.split(text) if part.strip()]

    def _resolve(self, segments: list[str]) -> list[Action] | None:
        actions: list[Action] = []
        last_verb: str | None = None
        for segment in segments[:MAX_STEPS]:
            intent, last_verb = self._parse_segment(segment, last_verb)
            if intent is None or intent.name not in CHAINABLE:
                return None
            actions.append(self._mapper.to_action(intent))
        return actions

    def _parse_segment(self, segment: str, last_verb: str | None) -> tuple[Intent | None, str | None]:
        tokens = segment.split()
        head = tokens[0] if tokens else ""
        if head in lx.ACTION_VERBS or head in {"зроби", "давай"}:
            return self._parse(segment), head
        direct = self._parse(segment)
        if direct is not None:
            return direct, last_verb
        if last_verb is not None:
            return self._parse(f"{last_verb} {segment}"), last_verb
        return None, last_verb
