from __future__ import annotations

import logging
import re
import threading
from collections.abc import Iterable

from jarvis.core.config import NluSection
from jarvis.core.errors import StorageError
from jarvis.core.models import Program, ProgramKind
from jarvis.nlu.fuzzy_matcher import Candidate, FuzzyMatcher
from jarvis.nlu.text_normalizer import TextNormalizer
from jarvis.nlu.transliteration import contains_cyrillic, latin_to_cyrillic
from jarvis.skills.apps.known_aliases import KNOWN_ALIASES, VENDOR_PREFIXES
from jarvis.storage.repositories.programs import ProgramRepository

logger = logging.getLogger(__name__)

KIND_WEIGHTS: dict[ProgramKind, float] = {
    ProgramKind.USER: 1.0,
    ProgramKind.STEAM: 1.0,
    ProgramKind.EPIC: 1.0,
    ProgramKind.SYSTEM: 0.995,
    ProgramKind.SHORTCUT: 0.99,
    ProgramKind.UWP: 0.98,
    ProgramKind.URL: 0.98,
    ProgramKind.EXECUTABLE: 0.96,
}

_VERSION = re.compile(r"\bv?\d+(?:\.\d+)+\b|\((?:[^)]*)\)|\b(?:x64|x86|64 bit|32 bit|64bit|32bit)\b")
_UKRAINIAN_ENDINGS = ("ою", "ею", "ом", "ем", "у", "ю", "а", "я", "і", "и", "е", "є", "о")


def clean_program_name(name: str) -> str:
    return " ".join(_VERSION.sub(" ", TextNormalizer.basic(name)).split())


def soft_stem(text: str) -> str:
    return " ".join(_stem_token(token) for token in text.split())


def _stem_token(token: str) -> str:
    if len(token) <= 3 or not contains_cyrillic(token):
        return token
    for ending in _UKRAINIAN_ENDINGS:
        if token.endswith(ending) and len(token) - len(ending) >= 3:
            return token[: -len(ending)]
    return token


class ProgramAliasBuilder:
    def build(self, name: str, extra: Iterable[str] = ()) -> dict[str, str]:
        normalized = clean_program_name(name)
        aliases: dict[str, str] = {}
        for alias in [normalized, *self._vendorless(normalized), *extra, *self._known(normalized)]:
            cleaned = clean_program_name(alias)
            if cleaned:
                aliases[alias] = cleaned
        for cleaned in list(aliases.values()):
            if not contains_cyrillic(cleaned):
                transliterated = latin_to_cyrillic(cleaned)
                aliases.setdefault(transliterated, transliterated)
        return aliases

    @staticmethod
    def _vendorless(normalized: str) -> list[str]:
        return [
            normalized[len(prefix) :]
            for prefix in VENDOR_PREFIXES
            if normalized.startswith(prefix) and len(normalized) > len(prefix) + 1
        ]

    @staticmethod
    def _known(normalized: str) -> list[str]:
        found: list[str] = []
        for pattern, aliases in KNOWN_ALIASES.items():
            if pattern == normalized or f" {pattern} " in f" {normalized} ":
                found.extend(aliases)
        return found


class ProgramCatalog:
    def __init__(
        self, repository: ProgramRepository, matcher: FuzzyMatcher, settings: NluSection
    ) -> None:
        self._repository = repository
        self._matcher = matcher
        self._settings = settings
        self._lock = threading.RLock()
        self._programs: tuple[Program, ...] = ()
        self._candidates: tuple[Candidate[Program], ...] = ()

    def reload(self) -> None:
        try:
            programs = tuple(self._repository.list_all())
        except StorageError:
            logger.exception("Не вдалося завантажити індекс програм")
            return
        candidates = tuple(self._candidate(program) for program in programs)
        with self._lock:
            self._programs = programs
            self._candidates = candidates

    def all(self) -> tuple[Program, ...]:
        with self._lock:
            return self._programs

    def find(self, query: str) -> Program | None:
        normalized = clean_program_name(query)
        if not normalized:
            return None
        with self._lock:
            candidates = self._candidates
        best = None
        for variant in dict.fromkeys((normalized, soft_stem(normalized))):
            match = self._matcher.best_match(variant, candidates, self._settings.program_threshold)
            if match is not None and (best is None or match.score > best.score):
                best = match
        return best.payload if best is not None else None

    def is_known_program(self, name: str) -> bool:
        return self.find(name) is not None

    def spoken_names(self) -> list[str]:
        names: list[str] = []
        for program in self.all():
            names.extend(alias for alias in program.aliases if contains_cyrillic(alias))
        return names

    @staticmethod
    def _candidate(program: Program) -> Candidate[Program]:
        variants = dict.fromkeys([program.normalized, *program.aliases])
        stemmed = [soft_stem(variant) for variant in variants]
        return Candidate(
            payload=program,
            variants=tuple(dict.fromkeys([*variants, *stemmed])),
            weight=KIND_WEIGHTS.get(program.kind, 0.95),
        )
