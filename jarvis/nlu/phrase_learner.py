from __future__ import annotations

import logging
from collections.abc import Iterable

from jarvis.core.config import NluSection
from jarvis.core.errors import StorageError
from jarvis.core.intent import Intent
from jarvis.core.models import AliasSource, Binding, BindingSource, VocabularyAlias
from jarvis.nlu.intent_actions import IntentActionMapper
from jarvis.nlu.pronunciation_matcher import WordDetection
from jarvis.storage.repositories.bindings import BindingRepository
from jarvis.storage.repositories.vocabulary import VocabularyRepository

logger = logging.getLogger(__name__)

MIN_LEARNED_PHRASE_LENGTH = 3


class PhraseLearner:
    def __init__(
        self,
        bindings: BindingRepository,
        mapper: IntentActionMapper,
    ) -> None:
        self._bindings = bindings
        self._mapper = mapper

    def learn(self, phrase: str, normalized: str, intent: Intent) -> Binding | None:
        if len(normalized) < MIN_LEARNED_PHRASE_LENGTH or not self._mapper.is_learnable(intent):
            return None
        if self._bindings.find_by_normalized(normalized) is not None:
            return None
        binding = Binding(
            id=None,
            phrase=phrase,
            normalized=normalized,
            action=self._mapper.to_action(intent),
            source=BindingSource.LEARNED,
        )
        try:
            saved = self._bindings.save(binding)
        except StorageError:
            logger.exception("Не вдалося зберегти вивчену фразу «%s»", phrase)
            return None
        logger.info("Вивчено нову фразу «%s» → %s", phrase, saved.action.describe())
        return saved


class AliasFeedback:
    def __init__(self, vocabulary: VocabularyRepository, settings: NluSection) -> None:
        self._vocabulary = vocabulary
        self._settings = settings

    def reinforce(self, detections: Iterable[WordDetection]) -> bool:
        changed = False
        for detection in detections:
            changed |= self._reinforce_one(detection)
        return changed

    def penalize(self, aliases: Iterable[VocabularyAlias]) -> bool:
        changed = False
        for alias in aliases:
            if alias.id is None:
                continue
            removed = self._vocabulary.penalize_alias(
                alias.id, self._settings.alias_penalty, self._settings.alias_min_weight
            )
            logger.info("Знижено вагу аліасу «%s»%s", alias.alias, " (видалено)" if removed else "")
            changed = True
        return changed

    def _reinforce_one(self, detection: WordDetection) -> bool:
        word_id = detection.word.id
        if word_id is None:
            return False
        if detection.alias is not None and detection.alias.id is not None:
            self._vocabulary.reinforce_alias(detection.alias.id, self._settings.alias_reward)
        if self._is_known_form(detection):
            return False
        self._vocabulary.upsert_alias(
            word_id, detection.matched_text, detection.matched_text, AliasSource.USAGE
        )
        logger.info("Новий аліас «%s» для слова «%s»", detection.matched_text, detection.word.text)
        return True

    @staticmethod
    def _is_known_form(detection: WordDetection) -> bool:
        known = {alias.normalized for alias in detection.word.aliases} | {detection.word.normalized}
        return detection.matched_text in known
