from __future__ import annotations

import logging

from jarvis.core.event_bus import EventBus
from jarvis.core.events import (
    BindingsChanged,
    BindingsListed,
    ProgramsIndexed,
    ProgramsListed,
    VocabularyChanged,
    VocabularyListed,
)
from jarvis.nlu.pipeline import BindingCatalog
from jarvis.nlu.pronunciation_matcher import VocabularyIndex
from jarvis.nlu.text_normalizer import TextNormalizer
from jarvis.skills.apps.catalog import ProgramCatalog
from jarvis.speech.grammar import GrammarProvider
from jarvis.speech.wake_word import WakeWordMatcher

logger = logging.getLogger(__name__)


class CatalogRefresher:
    def __init__(
        self,
        bus: EventBus,
        bindings: BindingCatalog,
        vocabulary: VocabularyIndex,
        programs: ProgramCatalog,
        grammar: GrammarProvider,
        wake_matcher: WakeWordMatcher,
    ) -> None:
        self._bus = bus
        self._bindings = bindings
        self._vocabulary = vocabulary
        self._programs = programs
        self._grammar = grammar
        self._wake_matcher = wake_matcher

    def start(self) -> None:
        self._bus.subscribe(BindingsChanged, lambda _: self.refresh_bindings())
        self._bus.subscribe(VocabularyChanged, lambda _: self.refresh_vocabulary())
        self._bus.subscribe(ProgramsIndexed, lambda _: self.refresh_programs())

    def refresh_all(self) -> None:
        self.refresh_bindings()
        self.refresh_vocabulary()
        self.refresh_programs()

    def refresh_bindings(self) -> None:
        self._bindings.reload()
        self._grammar.invalidate()
        self._bus.publish(BindingsListed(self._bindings.all()))

    def refresh_vocabulary(self) -> None:
        self._vocabulary.reload()
        self._grammar.invalidate()
        self._update_wake_variants()
        self._bus.publish(VocabularyListed(tuple(entry.word for entry in self._vocabulary.entries())))

    def refresh_programs(self) -> None:
        self._programs.reload()
        self._grammar.invalidate()
        self._bus.publish(ProgramsListed(self._programs.all()))

    def _update_wake_variants(self) -> None:
        learned: list[str] = []
        for entry in self._vocabulary.entries():
            if not any(self._wake_matcher.matches(part) for part in (entry.word.normalized, entry.word.text)):
                continue
            learned.extend(alias.normalized for alias in entry.word.aliases)
        self._wake_matcher.update_learned(TextNormalizer.basic(item) for item in learned)
        if learned:
            logger.info("Навчені варіанти wake word: %s", ", ".join(learned))
