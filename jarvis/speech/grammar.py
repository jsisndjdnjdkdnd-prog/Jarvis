from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterable, Sequence

from jarvis.nlu import lexicon as lx
from jarvis.nlu.durations import DAY_WORDS, HALF_WORDS, ONE_AND_HALF_WORDS
from jarvis.nlu.numbers import HOUR_ORDINALS, HUNDREDS, TEENS, TENS, UNITS
from jarvis.nlu.text_normalizer import TextNormalizer
from jarvis.nlu.time_parser import DAY_OFFSETS, WEEKDAYS

logger = logging.getLogger(__name__)

PhraseSource = Callable[[], Iterable[str]]

TIME_UNIT_WORDS: tuple[str, ...] = (
    "секунд", "секунду", "секунди", "хвилин", "хвилину", "хвилини", "годин", "годину", "години",
    "на", "через", "о", "об", "в", "у", "мені", "ранку", "вечора", "дня", "ночі",
)


def command_keywords() -> set[str]:
    words: set[str] = set()
    for collection in (
        lx.OPEN_VERBS, lx.TOGGLE_ON_VERBS, lx.PLAY_VERBS, lx.CLOSE_VERBS, lx.OFF_VERBS,
        lx.CANCEL_VERBS, lx.MUSIC_WORDS, lx.PRONOUNS, lx.PC_WORDS, lx.FOLDER_WORDS,
        lx.REMINDER_VERBS, lx.LEARN_VERBS, lx.LOCK_WORDS, lx.RESTART_WORDS,
        UNITS.keys(), TEENS.keys(), TENS.keys(), HUNDREDS.keys(), HOUR_ORDINALS.keys(),
        DAY_OFFSETS.keys(), WEEKDAYS.keys(), DAY_WORDS, HALF_WORDS, ONE_AND_HALF_WORDS,
        TIME_UNIT_WORDS,
    ):
        words.update(collection)
    for phrases in (
        lx.CONFIRM_PHRASES, lx.DENY_PHRASES, lx.CORRECTION_PHRASES, lx.GREETING_PHRASES,
        lx.THANKS_PHRASES, lx.TIME_PHRASES, lx.DATE_PHRASES, lx.TIMER_STATUS_PHRASES,
        lx.LIKE_PHRASES, lx.PAUSE_PHRASES, lx.RESUME_PHRASES, lx.NEXT_PHRASES,
        lx.NOW_PLAYING_PHRASES, lx.VOLUME_UP_PHRASES, lx.VOLUME_DOWN_PHRASES, lx.MUTE_PHRASES,
        lx.UNMUTE_PHRASES, lx.RESCAN_PHRASES, lx.REMINDER_LIST_PHRASES, lx.TIMER_WORDS,
        lx.SCREENSHOT_WORDS,
    ):
        words.update(phrases)
    return {word for word in words if word}


class GrammarProvider:
    def __init__(self, sources: Sequence[PhraseSource], static_phrases: Iterable[str]) -> None:
        self._sources = tuple(sources)
        self._static = tuple(sorted({TextNormalizer.basic(item) for item in static_phrases}))
        self._lock = threading.Lock()
        self._cached: tuple[str, ...] | None = None

    def invalidate(self) -> None:
        with self._lock:
            self._cached = None

    def phrases(self) -> tuple[str, ...]:
        with self._lock:
            if self._cached is None:
                self._cached = self._build()
            return self._cached

    def _build(self) -> tuple[str, ...]:
        collected: dict[str, None] = dict.fromkeys(self._static)
        for source in self._sources:
            for phrase in source():
                normalized = TextNormalizer.basic(phrase)
                if normalized:
                    collected[normalized] = None
        logger.debug("Grammar оновлено: %d фраз", len(collected))
        return tuple(collected)
