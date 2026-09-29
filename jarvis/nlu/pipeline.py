from __future__ import annotations

import logging
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from pydantic import ValidationError

from jarvis.core.config import NluSection
from jarvis.core.errors import DeepSeekError, StorageError
from jarvis.core.intent import Intent, IntentName, ResolutionStage
from jarvis.core.models import Binding
from jarvis.nlu.deepseek_intents import DeepSeekIntentResolver
from jarvis.nlu.fuzzy_matcher import Candidate, FuzzyMatcher
from jarvis.nlu.intent_parser import IntentParser
from jarvis.nlu.pronunciation_matcher import CanonicalUtterance
from jarvis.storage.repositories.bindings import BindingRepository
from jarvis.storage.repositories.deepseek import DeepSeekCacheRepository

logger = logging.getLogger(__name__)

NON_CACHEABLE: frozenset[IntentName] = frozenset(
    {
        IntentName.CHAT,
        IntentName.UNKNOWN,
        IntentName.CONFIRM,
        IntentName.DENY,
        IntentName.CORRECTION,
        IntentName.REMINDER_ADD,
    }
)


@dataclass(frozen=True)
class Resolution:
    intent: Intent
    stage: ResolutionStage
    matched_text: str
    binding: Binding | None = None
    score: float = 100.0


class ResolverStage(Protocol):
    def resolve(self, utterance: CanonicalUtterance) -> Resolution | None: ...


class BindingCatalog:
    def __init__(self, repository: BindingRepository) -> None:
        self._repository = repository
        self._lock = threading.RLock()
        self._bindings: tuple[Binding, ...] = ()

    def reload(self) -> None:
        try:
            bindings = tuple(self._repository.list_all())
        except StorageError:
            logger.exception("Не вдалося завантажити бінди")
            return
        with self._lock:
            self._bindings = bindings

    def all(self) -> tuple[Binding, ...]:
        with self._lock:
            return self._bindings

    def find_exact(self, normalized: str) -> Binding | None:
        for binding in self.all():
            if binding.normalized == normalized:
                return binding
        return None


def _binding_intent(binding: Binding) -> Intent:
    return Intent(name=IntentName.RUN_BINDING, binding_id=binding.id, phrase=binding.phrase)


class ExactBindingStage:
    def __init__(self, catalog: BindingCatalog) -> None:
        self._catalog = catalog

    def resolve(self, utterance: CanonicalUtterance) -> Resolution | None:
        for variant in utterance.variants:
            binding = self._catalog.find_exact(variant)
            if binding is not None:
                return Resolution(_binding_intent(binding), ResolutionStage.EXACT_BINDING, variant, binding)
        return None


class FuzzyBindingStage:
    def __init__(self, catalog: BindingCatalog, matcher: FuzzyMatcher, settings: NluSection) -> None:
        self._catalog = catalog
        self._matcher = matcher
        self._settings = settings

    def resolve(self, utterance: CanonicalUtterance) -> Resolution | None:
        candidates = [Candidate(binding, (binding.normalized,)) for binding in self._catalog.all()]
        if not candidates:
            return None
        best: Resolution | None = None
        for variant in utterance.variants:
            match = self._matcher.best_match(variant, candidates, self._settings.binding_threshold)
            if match is None or (best is not None and match.score <= best.score):
                continue
            best = Resolution(
                _binding_intent(match.payload),
                ResolutionStage.FUZZY_BINDING,
                variant,
                match.payload,
                match.score,
            )
        return best


class RuleStage:
    def __init__(self, parser: IntentParser) -> None:
        self._parser = parser

    def resolve(self, utterance: CanonicalUtterance) -> Resolution | None:
        for variant in utterance.variants:
            intent = self._parser.parse(variant)
            if intent is not None:
                return Resolution(intent, ResolutionStage.RULES, variant)
        return None


class DeepSeekCacheStage:
    def __init__(self, cache: DeepSeekCacheRepository) -> None:
        self._cache = cache

    def resolve(self, utterance: CanonicalUtterance) -> Resolution | None:
        for variant in utterance.variants:
            raw = self._cache.get(variant)
            if raw is None:
                continue
            try:
                intent = Intent.model_validate_json(raw)
            except ValidationError:
                logger.warning("Пошкоджений запис кешу DeepSeek для «%s» — видаляю", variant)
                self._cache.delete(variant)
                continue
            return Resolution(intent, ResolutionStage.DEEPSEEK_CACHE, variant)
        return None


class DeepSeekStage:
    def __init__(self, resolver: DeepSeekIntentResolver, cache: DeepSeekCacheRepository) -> None:
        self._resolver = resolver
        self._cache = cache

    def resolve(self, utterance: CanonicalUtterance) -> Resolution | None:
        if not self._resolver.available:
            return None
        intent = self._resolver.resolve(utterance.canonical)
        if intent.name is IntentName.UNKNOWN:
            return None
        if intent.name not in NON_CACHEABLE:
            self._cache.put(utterance.canonical, intent.model_dump_json(exclude_none=True))
        return Resolution(intent, ResolutionStage.DEEPSEEK, utterance.canonical)


class IntentPipeline:
    def __init__(self, stages: Sequence[ResolverStage]) -> None:
        self._stages = tuple(stages)

    def resolve(self, utterance: CanonicalUtterance) -> Resolution | None:
        if not utterance.canonical:
            return None
        for stage in self._stages:
            resolution = self._try(stage, utterance)
            if resolution is not None:
                logger.info(
                    "«%s» → %s [%s]",
                    utterance.canonical,
                    resolution.intent.name.value,
                    resolution.stage.value,
                )
                return resolution
        return None

    @staticmethod
    def _try(stage: ResolverStage, utterance: CanonicalUtterance) -> Resolution | None:
        try:
            return stage.resolve(utterance)
        except DeepSeekError as error:
            logger.warning("DeepSeek недоступний: %s", error)
        except StorageError:
            logger.exception("Помилка сховища на етапі %s", type(stage).__name__)
        return None
