from __future__ import annotations

import logging
import threading
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from jarvis.core.config import NluSection
from jarvis.core.errors import EmptyRecordingError, StorageError
from jarvis.core.models import VocabularyAlias, VocabularyWord
from jarvis.core.speech_types import RecognizedWord, Utterance
from jarvis.nlu.fuzzy_matcher import PhraseSimilarity
from jarvis.nlu.text_normalizer import TextNormalizer
from jarvis.storage.repositories.vocabulary import VocabularyRepository
from jarvis.training.voice_templates import (
    AcousticModel,
    DtwComparer,
    FeatureExtractor,
    deserialize_features,
)

logger = logging.getLogger(__name__)

SEGMENT_PADDING_SECONDS = 0.12


@dataclass(frozen=True)
class VocabularyEntry:
    word: VocabularyWord
    acoustic: AcousticModel | None


@dataclass(frozen=True)
class WordDetection:
    word: VocabularyWord
    alias: VocabularyAlias | None
    start_token: int
    end_token: int
    matched_text: str
    alias_score: float
    acoustic_score: float | None
    combined_score: float


@dataclass(frozen=True)
class CanonicalUtterance:
    original: str
    canonical: str
    detections: tuple[WordDetection, ...] = ()
    utterance: Utterance | None = None

    @property
    def used_aliases(self) -> tuple[VocabularyAlias, ...]:
        return tuple(detection.alias for detection in self.detections if detection.alias is not None)

    @property
    def variants(self) -> tuple[str, ...]:
        if self.canonical == self.original:
            return (self.canonical,)
        return (self.canonical, self.original)


@dataclass(frozen=True)
class _Window:
    start: int
    end: int
    text: str


class VocabularyIndex:
    def __init__(self, repository: VocabularyRepository) -> None:
        self._repository = repository
        self._lock = threading.RLock()
        self._entries: tuple[VocabularyEntry, ...] = ()

    def reload(self) -> None:
        try:
            words = self._repository.list_words()
        except StorageError:
            logger.exception("Не вдалося завантажити словник вимови")
            return
        entries = tuple(VocabularyEntry(word, self._load_acoustic(word)) for word in words)
        with self._lock:
            self._entries = entries
        logger.info("Словник вимови: %d слів", len(entries))

    def entries(self) -> tuple[VocabularyEntry, ...]:
        with self._lock:
            return self._entries

    def entry(self, word_id: int) -> VocabularyEntry | None:
        for entry in self.entries():
            if entry.word.id == word_id:
                return entry
        return None

    def _load_acoustic(self, word: VocabularyWord) -> AcousticModel | None:
        if word.id is None or not word.acoustic_threshold:
            return None
        templates = [
            deserialize_features(sample.features)
            for sample in self._repository.list_samples(word.id)
            if sample.features
        ]
        if not templates:
            return None
        return AcousticModel(templates=tuple(templates), threshold=float(word.acoustic_threshold))


class PronunciationScorer:
    def __init__(
        self,
        similarity: PhraseSimilarity,
        extractor: FeatureExtractor,
        comparer: DtwComparer,
        settings: NluSection,
    ) -> None:
        self._similarity = similarity
        self._extractor = extractor
        self._comparer = comparer
        self._settings = settings

    def alias_score(self, text: str, word: VocabularyWord) -> tuple[float, VocabularyAlias | None]:
        best = self._similarity.compact_score(text, word.normalized) / 100.0
        best_alias: VocabularyAlias | None = None
        for alias in word.aliases:
            score = self._similarity.compact_score(text, alias.normalized) / 100.0 * alias.weight
            if score > best:
                best = score
                best_alias = alias
        return best, best_alias

    def acoustic_score(
        self, model: AcousticModel | None, pcm: bytes | None, sample_rate: int
    ) -> float | None:
        if model is None or not pcm:
            return None
        try:
            features = self._extractor.extract(pcm, sample_rate)
        except EmptyRecordingError:
            return None
        return model.similarity(features, self._comparer)

    def combine(self, alias_score: float, acoustic_score: float | None) -> float:
        if acoustic_score is None:
            return alias_score
        alias_weight = self._settings.alias_weight
        acoustic_weight = self._settings.acoustic_weight
        return (alias_weight * alias_score + acoustic_weight * acoustic_score) / (
            alias_weight + acoustic_weight
        )

    def is_match(self, alias_score: float, acoustic_score: float | None, combined: float) -> bool:
        if acoustic_score is None:
            return alias_score * 100.0 >= self._settings.alias_threshold
        return combined >= self._settings.vocabulary_decision_threshold


class PronunciationMatcher:
    def __init__(
        self,
        index: VocabularyIndex,
        scorer: PronunciationScorer,
        normalizer: TextNormalizer,
        settings: NluSection,
    ) -> None:
        self._index = index
        self._scorer = scorer
        self._normalizer = normalizer
        self._settings = settings

    def rewrite(self, text: str, utterance: Utterance | None = None) -> CanonicalUtterance:
        entries = self._index.entries()
        tokens = text.split()
        if not entries or not tokens:
            return CanonicalUtterance(text, text, (), utterance)
        timings = self._align(tokens, utterance)
        detections = self._select(self._detect(tokens, timings, entries, utterance))
        canonical = self._apply(tokens, detections)
        return CanonicalUtterance(text, canonical, tuple(detections), utterance)

    def _detect(
        self,
        tokens: Sequence[str],
        timings: Sequence[RecognizedWord | None],
        entries: Sequence[VocabularyEntry],
        utterance: Utterance | None,
    ) -> list[WordDetection]:
        detections: list[WordDetection] = []
        for window in self._windows(tokens):
            for entry in entries:
                detection = self._evaluate(window, entry, timings, utterance)
                if detection is not None:
                    detections.append(detection)
        return detections

    def _evaluate(
        self,
        window: _Window,
        entry: VocabularyEntry,
        timings: Sequence[RecognizedWord | None],
        utterance: Utterance | None,
    ) -> WordDetection | None:
        alias_score, alias = self._scorer.alias_score(window.text, entry.word)
        if alias_score * 100.0 < self._settings.alias_prefilter:
            return None
        segment = self._segment(window, timings, utterance)
        sample_rate = utterance.sample_rate if utterance is not None else 16000
        acoustic = self._scorer.acoustic_score(entry.acoustic, segment, sample_rate)
        combined = self._scorer.combine(alias_score, acoustic)
        if not self._scorer.is_match(alias_score, acoustic, combined):
            return None
        return WordDetection(
            word=entry.word,
            alias=alias,
            start_token=window.start,
            end_token=window.end,
            matched_text=window.text,
            alias_score=alias_score,
            acoustic_score=acoustic,
            combined_score=combined,
        )

    def _windows(self, tokens: Sequence[str]) -> list[_Window]:
        windows: list[_Window] = []
        for start in range(len(tokens)):
            for size in range(1, self._settings.alias_max_window + 1):
                end = start + size
                if end > len(tokens):
                    break
                windows.append(_Window(start, end, " ".join(tokens[start:end])))
        return windows

    @staticmethod
    def _select(detections: list[WordDetection]) -> list[WordDetection]:
        ranked = sorted(
            detections,
            key=lambda item: (item.combined_score, -(item.end_token - item.start_token)),
            reverse=True,
        )
        taken: set[int] = set()
        selected: list[WordDetection] = []
        for detection in ranked:
            span = set(range(detection.start_token, detection.end_token))
            if span & taken:
                continue
            taken |= span
            selected.append(detection)
        return sorted(selected, key=lambda item: item.start_token)

    @staticmethod
    def _apply(tokens: Sequence[str], detections: Sequence[WordDetection]) -> str:
        output: list[str] = []
        index = 0
        for detection in detections:
            output.extend(tokens[index : detection.start_token])
            output.append(detection.word.normalized)
            index = detection.end_token
        output.extend(tokens[index:])
        return " ".join(output)

    def _align(
        self, tokens: Sequence[str], utterance: Utterance | None
    ) -> list[RecognizedWord | None]:
        if utterance is None or not utterance.transcript.words:
            return [None] * len(tokens)
        words = list(utterance.transcript.words)
        aligned: list[RecognizedWord | None] = []
        pointer = 0
        for token in tokens:
            match_index = self._find_word(words, pointer, token)
            if match_index is None:
                aligned.append(None)
                continue
            aligned.append(words[match_index])
            pointer = match_index + 1
        return aligned

    def _find_word(self, words: Sequence[RecognizedWord], start: int, token: str) -> int | None:
        for index in range(start, len(words)):
            if self._normalizer.basic(words[index].text) == token:
                return index
        return None

    @staticmethod
    def _segment(
        window: _Window,
        timings: Sequence[RecognizedWord | None],
        utterance: Utterance | None,
    ) -> bytes | None:
        if utterance is None or utterance.audio is None:
            return None
        first = timings[window.start]
        last = timings[window.end - 1]
        if first is None or last is None:
            return None
        rate = utterance.sample_rate
        begin = max(0, int((first.start - SEGMENT_PADDING_SECONDS) * rate))
        finish = int((last.end + SEGMENT_PADDING_SECONDS) * rate)
        samples = np.frombuffer(utterance.audio, dtype=np.int16)
        return samples[begin : min(finish, len(samples))].tobytes()
