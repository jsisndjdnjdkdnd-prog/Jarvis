from __future__ import annotations

from jarvis.core.config import NluSection
from jarvis.core.errors import DeepSeekError
from jarvis.core.intent import Action, ActionType, Intent, IntentName, ResolutionStage
from jarvis.core.models import Binding
from jarvis.nlu.fuzzy_matcher import FuzzyMatcher
from jarvis.nlu.intent_parser import IntentParser
from jarvis.nlu.pipeline import (
    BindingCatalog,
    DeepSeekCacheStage,
    DeepSeekStage,
    ExactBindingStage,
    FuzzyBindingStage,
    IntentPipeline,
    RuleStage,
)
from jarvis.nlu.pronunciation_matcher import CanonicalUtterance
from jarvis.storage.repositories import Repositories


class FakeResolver:
    def __init__(self, intent: Intent | None = None, error: bool = False) -> None:
        self.calls: list[str] = []
        self._intent = intent
        self._error = error

    @property
    def available(self) -> bool:
        return True

    def resolve(self, text: str) -> Intent:
        self.calls.append(text)
        if self._error or self._intent is None:
            raise DeepSeekError("offline")
        return self._intent


def build_pipeline(repositories: Repositories, parser: IntentParser, resolver: FakeResolver) -> IntentPipeline:
    catalog = BindingCatalog(repositories.bindings)
    catalog.reload()
    return IntentPipeline(
        (
            ExactBindingStage(catalog),
            FuzzyBindingStage(catalog, FuzzyMatcher(), NluSection()),
            RuleStage(parser),
            DeepSeekCacheStage(repositories.deepseek_cache),
            DeepSeekStage(resolver, repositories.deepseek_cache),
        )
    )


def utterance(text: str) -> CanonicalUtterance:
    return CanonicalUtterance(original=text, canonical=text)


def test_exact_binding_wins_over_rules(repositories: Repositories, parser: IntentParser) -> None:
    repositories.bindings.save(
        Binding(None, "відкрий дотку", "відкрий дотку", Action(type=ActionType.LAUNCH, target="steam://rungameid/570"))
    )
    resolver = FakeResolver()
    resolution = build_pipeline(repositories, parser, resolver).resolve(utterance("відкрий дотку"))
    assert resolution.stage is ResolutionStage.EXACT_BINDING
    assert resolution.intent.name is IntentName.RUN_BINDING
    assert resolver.calls == []


def test_fuzzy_binding_before_rules(repositories: Repositories, parser: IntentParser) -> None:
    repositories.bindings.save(
        Binding(None, "відкрий дотку", "відкрий дотку", Action(type=ActionType.LAUNCH, target="steam://rungameid/570"))
    )
    resolution = build_pipeline(repositories, parser, FakeResolver()).resolve(utterance("відкрий дотка"))
    assert resolution.stage is ResolutionStage.FUZZY_BINDING


def test_rules_before_deepseek(repositories: Repositories, parser: IntentParser) -> None:
    resolver = FakeResolver(Intent(name=IntentName.CHAT, reply="ні"))
    resolution = build_pipeline(repositories, parser, resolver).resolve(utterance("котра година"))
    assert resolution.stage is ResolutionStage.RULES
    assert resolver.calls == []


def test_deepseek_result_is_cached(repositories: Repositories, parser: IntentParser) -> None:
    resolver = FakeResolver(Intent(name=IntentName.OPEN_APP, target="spotify"))
    pipeline = build_pipeline(repositories, parser, resolver)
    first = pipeline.resolve(utterance("хочу послухати спотіфай"))
    second = pipeline.resolve(utterance("хочу послухати спотіфай"))
    assert first.stage is ResolutionStage.DEEPSEEK
    assert second.stage is ResolutionStage.DEEPSEEK_CACHE
    assert second.intent.target == "spotify"
    assert len(resolver.calls) == 1


def test_chat_is_not_cached(repositories: Repositories, parser: IntentParser) -> None:
    resolver = FakeResolver(Intent(name=IntentName.CHAT, reply="Це розділ фізики, сер."))
    pipeline = build_pipeline(repositories, parser, resolver)
    pipeline.resolve(utterance("поясни квантову фізику"))
    pipeline.resolve(utterance("поясни квантову фізику"))
    assert len(resolver.calls) == 2


def test_deepseek_failure_returns_none(repositories: Repositories, parser: IntentParser) -> None:
    resolution = build_pipeline(repositories, parser, FakeResolver(error=True)).resolve(utterance("бла бла"))
    assert resolution is None
