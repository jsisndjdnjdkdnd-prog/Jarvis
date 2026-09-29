from __future__ import annotations

import pytest

from jarvis.core.config import NluSection
from jarvis.core.models import AliasSource, VocabularyAlias, VocabularyWord
from jarvis.nlu.fuzzy_matcher import Candidate, FuzzyMatcher, PhraseSimilarity
from jarvis.nlu.pronunciation_matcher import (
    PronunciationMatcher,
    PronunciationScorer,
    VocabularyEntry,
)
from jarvis.nlu.text_normalizer import TextNormalizer
from jarvis.nlu.transliteration import cyrillic_to_latin, latin_to_cyrillic, phonetic_key
from jarvis.training.voice_templates import DtwComparer, MfccExtractor


@pytest.fixture
def matcher() -> FuzzyMatcher:
    return FuzzyMatcher()


def candidates(*phrases: str) -> list[Candidate[str]]:
    return [Candidate(payload=phrase, variants=(phrase,)) for phrase in phrases]


def test_exact_phrase_scores_100(matcher: FuzzyMatcher) -> None:
    match = matcher.best_match("бойовий режим", candidates("бойовий режим", "робочий день"), threshold=80)
    assert match is not None
    assert match.payload == "бойовий режим"
    assert match.score == 100


def test_extra_words_still_match(matcher: FuzzyMatcher) -> None:
    match = matcher.best_match("увімкни бойовий режим", candidates("бойовий режим"), threshold=80)
    assert match is not None


def test_recognition_typo_matches(matcher: FuzzyMatcher) -> None:
    match = matcher.best_match("відкрий дотка", candidates("відкрий дотку", "відкрий хром"), threshold=80)
    assert match is not None
    assert match.payload == "відкрий дотку"


def test_partial_command_is_rejected(matcher: FuzzyMatcher) -> None:
    assert matcher.best_match("відкрий", candidates("відкрий дотку"), threshold=80) is None


def test_different_object_is_rejected(matcher: FuzzyMatcher) -> None:
    assert matcher.best_match("відкрий хром", candidates("відкрий дотку"), threshold=80) is None


def test_cross_script_matching_via_phonetics(matcher: FuzzyMatcher) -> None:
    match = matcher.best_match("діскорд", candidates("discord", "telegram"), threshold=75)
    assert match is not None
    assert match.payload == "discord"


def test_weight_lowers_score(matcher: FuzzyMatcher) -> None:
    weighted = [Candidate(payload="a", variants=("бойовий режим",), weight=0.5)]
    assert matcher.best_match("бойовий режим", weighted, threshold=80) is None


def test_transliteration_roundtrip_is_readable() -> None:
    assert cyrillic_to_latin("хром") == "khrom"
    assert latin_to_cyrillic("chrome").startswith("ч")
    assert phonetic_key("хром") == phonetic_key("chrom")


class StaticIndex:
    def __init__(self, entries: tuple[VocabularyEntry, ...]) -> None:
        self._entries = entries

    def entries(self) -> tuple[VocabularyEntry, ...]:
        return self._entries


def make_word(text: str, aliases: tuple[str, ...], weight: float = 1.0) -> VocabularyWord:
    return VocabularyWord(
        id=1,
        text=text,
        normalized=text.lower(),
        aliases=tuple(
            VocabularyAlias(id=index, word_id=1, alias=alias, normalized=alias, weight=weight, source=AliasSource.TRAINING)
            for index, alias in enumerate(aliases, start=1)
        ),
    )


def build_matcher(word: VocabularyWord) -> PronunciationMatcher:
    settings = NluSection()
    similarity = PhraseSimilarity()
    scorer = PronunciationScorer(similarity, MfccExtractor(), DtwComparer(), settings)
    index = StaticIndex((VocabularyEntry(word=word, acoustic=None),))
    return PronunciationMatcher(index, scorer, TextNormalizer(), settings)


def test_trained_alias_rewrites_multiword_window() -> None:
    matcher = build_matcher(make_word("Malwarebytes", ("мал вер байтс", "малвар байт")))
    result = matcher.rewrite("відкрий мал вер байтс")
    assert result.canonical == "відкрий malwarebytes"
    assert result.used_aliases[0].alias == "мал вер байтс"


def test_similar_but_unseen_variant_is_detected() -> None:
    matcher = build_matcher(make_word("Malwarebytes", ("мал вер байтс",)))
    result = matcher.rewrite("запусти малвер байтс")
    assert result.canonical == "запусти malwarebytes"
    assert result.detections[0].matched_text == "малвер байтс"


def test_rewrite_keeps_unrelated_text() -> None:
    matcher = build_matcher(make_word("Malwarebytes", ("мал вер байтс",)))
    result = matcher.rewrite("котра година")
    assert result.canonical == "котра година"
    assert result.detections == ()


def test_penalized_alias_stops_matching() -> None:
    trusted = build_matcher(make_word("Колега", ("бро",), weight=1.0))
    penalized = build_matcher(make_word("Колега", ("бро",), weight=0.3))
    assert trusted.rewrite("привіт бро").canonical == "привіт колега"
    assert penalized.rewrite("привіт бро").detections == ()
