from __future__ import annotations

import logging

from jarvis.core.assistant import Interpretation
from jarvis.core.errors import StorageError
from jarvis.core.event_bus import EventBus
from jarvis.core.events import BindingsChanged, VocabularyChanged
from jarvis.core.intent import ResolutionStage
from jarvis.core.models import VocabularyAlias
from jarvis.core.speech_types import Utterance
from jarvis.nlu.phrase_learner import AliasFeedback, PhraseLearner
from jarvis.nlu.pipeline import IntentPipeline, Resolution
from jarvis.nlu.pronunciation_matcher import CanonicalUtterance, PronunciationMatcher
from jarvis.nlu.text_normalizer import TextNormalizer

logger = logging.getLogger(__name__)

REMOTE_STAGES: frozenset[ResolutionStage] = frozenset(
    {ResolutionStage.DEEPSEEK, ResolutionStage.DEEPSEEK_CACHE}
)


class NluInterpreter:
    def __init__(
        self,
        normalizer: TextNormalizer,
        matcher: PronunciationMatcher,
        pipeline: IntentPipeline,
        learner: PhraseLearner,
        feedback: AliasFeedback,
        bus: EventBus,
    ) -> None:
        self._normalizer = normalizer
        self._matcher = matcher
        self._pipeline = pipeline
        self._learner = learner
        self._feedback = feedback
        self._bus = bus

    def normalize(self, text: str) -> str:
        return self._normalizer.normalize(text)

    def interpret(self, text: str, utterance: Utterance | None) -> Interpretation | None:
        normalized = self.normalize(text)
        if not normalized:
            return None
        canonical = self._matcher.rewrite(normalized, utterance)
        resolution = self._pipeline.resolve(canonical)
        if resolution is None:
            return None
        return Interpretation(
            text=text,
            normalized=canonical.canonical,
            intent=resolution.intent,
            stage=resolution.stage,
            used_aliases=canonical.used_aliases,
            feedback=lambda success: self._learn(canonical, resolution, success),
        )

    def penalize(self, aliases: tuple[VocabularyAlias, ...]) -> None:
        try:
            changed = self._feedback.penalize(aliases)
        except StorageError:
            logger.exception("Не вдалося знизити вагу аліасів")
            return
        if changed:
            self._bus.publish(VocabularyChanged())

    def _learn(self, canonical: CanonicalUtterance, resolution: Resolution, success: bool) -> None:
        if not success:
            return
        try:
            if self._feedback.reinforce(canonical.detections):
                self._bus.publish(VocabularyChanged())
            if resolution.stage in REMOTE_STAGES:
                self._learn_phrase(canonical, resolution)
        except StorageError:
            logger.exception("Самонавчання не вдалося")

    def _learn_phrase(self, canonical: CanonicalUtterance, resolution: Resolution) -> None:
        binding = self._learner.learn(canonical.canonical, canonical.canonical, resolution.intent)
        if binding is not None:
            self._bus.publish(BindingsChanged())
