from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Generic, TypeVar

from rapidfuzz import fuzz

from jarvis.nlu.transliteration import phonetic_key

T = TypeVar("T")

TOKEN_MATCH_FLOOR = 50.0


@dataclass(frozen=True)
class Candidate(Generic[T]):
    payload: T
    variants: tuple[str, ...]
    weight: float = 1.0


@dataclass(frozen=True)
class FuzzyMatch(Generic[T]):
    payload: T
    score: float
    matched_variant: str


class PhraseSimilarity:
    def score(self, query: str, variant: str) -> float:
        if not query or not variant:
            return 0.0
        if query == variant:
            return 100.0
        direct = self._weighted(query, variant)
        phonetic = self._weighted(phonetic_key(query), phonetic_key(variant))
        compact = fuzz.ratio(query.replace(" ", ""), variant.replace(" ", ""))
        return max(direct, phonetic, compact)

    def compact_score(self, query: str, variant: str) -> float:
        if not query or not variant:
            return 0.0
        direct = fuzz.ratio(query.replace(" ", ""), variant.replace(" ", ""))
        phonetic = fuzz.ratio(
            phonetic_key(query).replace(" ", ""), phonetic_key(variant).replace(" ", "")
        )
        return max(direct, phonetic)

    def _weighted(self, query: str, variant: str) -> float:
        if not query or not variant:
            return 0.0
        base = fuzz.token_ratio(query, variant)
        return base * self._coverage(query.split(), variant.split())

    @staticmethod
    def _coverage(query_tokens: Sequence[str], variant_tokens: Sequence[str]) -> float:
        if not variant_tokens:
            return 0.0
        total = 0.0
        for token in variant_tokens:
            best = max((fuzz.ratio(token, other) for other in query_tokens), default=0.0)
            total += best if best >= TOKEN_MATCH_FLOOR else 0.0
        return total / (100.0 * len(variant_tokens))


class FuzzyMatcher:
    def __init__(self, similarity: PhraseSimilarity | None = None) -> None:
        self._similarity = similarity or PhraseSimilarity()

    def score(self, query: str, variant: str) -> float:
        return self._similarity.score(query, variant)

    def best_match(
        self, query: str, candidates: Iterable[Candidate[T]], threshold: float
    ) -> FuzzyMatch[T] | None:
        ranked = self.rank(query, candidates, threshold, limit=1)
        return ranked[0] if ranked else None

    def rank(
        self,
        query: str,
        candidates: Iterable[Candidate[T]],
        threshold: float,
        limit: int = 5,
    ) -> list[FuzzyMatch[T]]:
        matches: list[FuzzyMatch[T]] = []
        for candidate in candidates:
            match = self._score_candidate(query, candidate)
            if match is not None and match.score >= threshold:
                matches.append(match)
        matches.sort(key=lambda match: match.score, reverse=True)
        return matches[:limit]

    def _score_candidate(self, query: str, candidate: Candidate[T]) -> FuzzyMatch[T] | None:
        best_score = 0.0
        best_variant = ""
        for variant in candidate.variants:
            score = self._similarity.score(query, variant) * candidate.weight
            if score > best_score:
                best_score = score
                best_variant = variant
        if not best_variant:
            return None
        return FuzzyMatch(candidate.payload, best_score, best_variant)
