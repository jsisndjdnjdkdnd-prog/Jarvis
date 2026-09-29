from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any

from jarvis.core.config import SpeechSection
from jarvis.core.errors import ModelNotFoundError, RecognitionError
from jarvis.core.speech_types import RecognizedWord, Transcript

logger = logging.getLogger(__name__)

UNKNOWN_TOKEN = "[unk]"
CHUNK_BYTES = 8000


class VoskModelProvider:
    def __init__(self, model_paths: dict[str, Path]) -> None:
        self._paths = model_paths
        self._models: dict[str, Any] = {}
        self._vocabularies: dict[str, frozenset[str] | None] = {}
        self._lock = threading.Lock()

    @property
    def languages(self) -> tuple[str, ...]:
        return tuple(language for language, path in self._paths.items() if path.exists())

    def model(self, language: str) -> Any:
        with self._lock:
            if language not in self._models:
                self._models[language] = self._load(language)
            return self._models[language]

    def supports_grammar(self, language: str) -> bool:
        path = self._paths.get(language)
        if path is None:
            return False
        graph = path / "graph"
        return (graph / "HCLr.fst").exists() and (graph / "Gr.fst").exists()

    def vocabulary(self, language: str) -> frozenset[str] | None:
        with self._lock:
            if language not in self._vocabularies:
                self._vocabularies[language] = self._read_vocabulary(language)
            return self._vocabularies[language]

    def _load(self, language: str) -> Any:
        import vosk

        path = self._paths.get(language)
        if path is None or not path.exists():
            raise ModelNotFoundError(
                f"Модель Vosk для «{language}» не знайдена: {path}. Завантажте її з alphacephei.com/vosk/models"
            )
        vosk.SetLogLevel(-1)
        logger.info("Завантаження моделі Vosk %s з %s", language, path)
        try:
            return vosk.Model(str(path))
        except Exception as error:
            raise RecognitionError(f"Не вдалося завантажити модель {path}: {error}") from error

    def _read_vocabulary(self, language: str) -> frozenset[str] | None:
        path = self._paths.get(language)
        if path is None:
            return None
        words_file = path / "graph" / "words.txt"
        if not words_file.exists():
            return None
        words = set()
        with words_file.open(encoding="utf-8") as handle:
            for line in handle:
                token = line.split(" ", 1)[0].strip()
                if token and not token.startswith(("<", "#")):
                    words.add(token)
        return frozenset(words)


class VoskResultParser:
    def parse(self, raw: str, language: str) -> Transcript:
        data = json.loads(raw) if raw else {}
        if "alternatives" in data:
            return self._parse_alternatives(data["alternatives"], language)
        words = tuple(self._word(item) for item in data.get("result", []))
        text = str(data.get("text", "")).strip()
        return Transcript(text=text, words=words, language=language)

    def partial_text(self, raw: str) -> str:
        data = json.loads(raw) if raw else {}
        return str(data.get("partial", "")).strip()

    def _parse_alternatives(self, alternatives: list[dict[str, Any]], language: str) -> Transcript:
        if not alternatives:
            return Transcript(text="", language=language)
        best = alternatives[0]
        confidence = self._alternative_confidence(alternatives)
        words = tuple(
            RecognizedWord(
                text=str(item.get("word", "")),
                start=float(item.get("start", 0.0)),
                end=float(item.get("end", 0.0)),
                confidence=confidence,
            )
            for item in best.get("result", [])
        )
        texts = tuple(
            dict.fromkeys(str(item.get("text", "")).strip() for item in alternatives if item.get("text"))
        )
        return Transcript(text=str(best.get("text", "")).strip(), words=words, language=language, alternatives=texts)

    @staticmethod
    def _alternative_confidence(alternatives: list[dict[str, Any]]) -> float:
        scores = [float(item.get("confidence", 0.0)) for item in alternatives]
        if len(scores) < 2 or scores[0] <= 0:
            return 1.0
        return max(0.0, min(1.0, 1.0 - scores[1] / scores[0] + 0.5))

    @staticmethod
    def _word(item: dict[str, Any]) -> RecognizedWord:
        return RecognizedWord(
            text=str(item.get("word", "")),
            start=float(item.get("start", 0.0)),
            end=float(item.get("end", 0.0)),
            confidence=float(item.get("conf", 1.0)),
        )


class VoskRecognizerFactory:
    def __init__(self, models: VoskModelProvider, sample_rate: int) -> None:
        self._models = models
        self._sample_rate = sample_rate

    def create(
        self, language: str, grammar: Sequence[str] | None = None, alternatives: int = 0
    ) -> Any:
        import vosk

        model = self._models.model(language)
        usable_grammar = self._filter_grammar(language, grammar)
        if usable_grammar:
            recognizer = vosk.KaldiRecognizer(
                model, self._sample_rate, json.dumps(usable_grammar, ensure_ascii=False)
            )
        else:
            recognizer = vosk.KaldiRecognizer(model, self._sample_rate)
        recognizer.SetWords(True)
        if alternatives > 0:
            recognizer.SetMaxAlternatives(alternatives)
        return recognizer

    def _filter_grammar(self, language: str, grammar: Sequence[str] | None) -> list[str] | None:
        if not grammar or not self._models.supports_grammar(language):
            return None
        vocabulary = self._models.vocabulary(language)
        phrases = [phrase for phrase in grammar if self._phrase_supported(phrase, vocabulary)]
        if UNKNOWN_TOKEN not in phrases:
            phrases.append(UNKNOWN_TOKEN)
        return phrases if len(phrases) > 1 else None

    @staticmethod
    def _phrase_supported(phrase: str, vocabulary: frozenset[str] | None) -> bool:
        if phrase == UNKNOWN_TOKEN or vocabulary is None:
            return True
        return all(word in vocabulary for word in phrase.split())


class SpeechTranscriber:
    def __init__(
        self,
        factory: VoskRecognizerFactory,
        parser: VoskResultParser,
        settings: SpeechSection,
        models: VoskModelProvider,
    ) -> None:
        self._factory = factory
        self._parser = parser
        self._settings = settings
        self._models = models

    def transcribe(
        self,
        pcm: bytes,
        language: str | None = None,
        grammar: Sequence[str] | None = None,
        alternatives: int = 0,
    ) -> Transcript:
        target = language or self._settings.primary_language
        recognizer = self._factory.create(target, grammar, alternatives)
        pieces: list[Transcript] = []
        for offset in range(0, len(pcm), CHUNK_BYTES):
            if recognizer.AcceptWaveform(pcm[offset : offset + CHUNK_BYTES]):
                pieces.append(self._parser.parse(recognizer.Result(), target))
        pieces.append(self._parser.parse(recognizer.FinalResult(), target))
        return self._merge(pieces, target)

    def transcribe_command(self, pcm: bytes, grammar: Sequence[str] | None) -> Transcript:
        primary = self._settings.primary_language
        if grammar and self._settings.grammar_enabled and self._models.supports_grammar(primary):
            constrained = self.transcribe(pcm, primary, grammar)
            if self.is_reliable(constrained):
                logger.debug("Grammar-розпізнавання: %s", constrained.text)
                return constrained
        free = self.transcribe(pcm, primary)
        if free.confidence >= self._settings.secondary_min_confidence and not free.is_empty:
            return free
        return self._best_of([free, *self._secondary(pcm)])

    def is_reliable(self, transcript: Transcript) -> bool:
        if transcript.is_empty or UNKNOWN_TOKEN in transcript.text:
            return False
        return transcript.confidence >= self._settings.min_word_confidence

    def _secondary(self, pcm: bytes) -> Iterable[Transcript]:
        available = set(self._models.languages)
        for language in self._settings.secondary_languages:
            if language not in available:
                continue
            try:
                yield self.transcribe(pcm, language)
            except RecognitionError:
                logger.exception("Вторинна модель %s недоступна", language)

    @staticmethod
    def _best_of(transcripts: Sequence[Transcript]) -> Transcript:
        meaningful = [item for item in transcripts if not item.is_empty]
        if not meaningful:
            return transcripts[0]
        return max(meaningful, key=lambda item: item.confidence)

    @staticmethod
    def _merge(pieces: Sequence[Transcript], language: str) -> Transcript:
        non_empty = [piece for piece in pieces if not piece.is_empty]
        if not non_empty:
            return Transcript(text="", language=language)
        words = tuple(word for piece in non_empty for word in piece.words)
        text = " ".join(piece.text for piece in non_empty)
        alternatives = tuple(alt for piece in non_empty for alt in piece.alternatives)
        return Transcript(text=text, words=words, language=language, alternatives=alternatives)


class StreamingRecognizer:
    def __init__(
        self,
        factory: Callable[[], Any],
        parser: VoskResultParser,
        language: str,
    ) -> None:
        self._factory = factory
        self._parser = parser
        self._language = language
        self._recognizer = factory()

    def reset(self) -> None:
        self._recognizer = self._factory()

    def accept(self, chunk: bytes) -> Transcript | None:
        if self._recognizer.AcceptWaveform(chunk):
            return self._parser.parse(self._recognizer.Result(), self._language)
        return None

    def partial(self) -> str:
        return self._parser.partial_text(self._recognizer.PartialResult())
