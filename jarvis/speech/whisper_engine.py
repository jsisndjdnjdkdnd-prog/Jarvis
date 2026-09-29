from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx
import numpy as np

from jarvis.core.config import WhisperSection
from jarvis.core.errors import ModelNotFoundError, RecognitionError
from jarvis.core.speech_types import RecognizedWord, Transcript
from jarvis.speech.audio_preprocess import AudioPreprocessor, pcm_to_float32, resample
from jarvis.speech.transcriber import Transcriber

logger = logging.getLogger(__name__)

WHISPER_SAMPLE_RATE = 16000
CPU_DEVICE = "cpu"
AUTO_LANGUAGE = "auto"
FALLBACK_LANGUAGE = "uk"
DECODING_TEMPERATURE = 0.0
DEFAULT_RETRY_SECONDS = 60.0

HINT_CONTEXT = "Голосові команди асистенту Джарвіс:"
HINT_MAX_CHARS = 600
HINT_MIN_WORD_LENGTH = 4
HINT_SEPARATOR_COST = 2

SPECIFIC_PHRASE_TIER = 0
SPECIFIC_WORD_TIER = 1
COMMON_PHRASE_TIER = 2
COMMON_WORD_TIER = 3

UKRAINIAN_LANGUAGE = "uk"
UKRAINIAN_LETTERS = "абвгґдеєжзиіїйклмнопрстуфхцчшщьюя"
RUSSIAN_ONLY_LETTERS = "ыэъё"
_HINT_KEY_TRANSLATION = str.maketrans({"’": "'", "ʼ": "'", "`": "'", "‘": "'", "-": " "})


@dataclass(frozen=True)
class HintScript:
    required_letters: str = ""
    forbidden_letters: str = ""

    def accepts(self, phrase: str) -> bool:
        if self.required_letters and not any(letter in self.required_letters for letter in phrase):
            return False
        return not any(letter in self.forbidden_letters for letter in phrase)


UKRAINIAN_SCRIPT = HintScript(UKRAINIAN_LETTERS, RUSSIAN_ONLY_LETTERS)
ANY_SCRIPT = HintScript()

GENERIC_HINT_WORDS: frozenset[str] = frozenset(
    {
        "будь", "ласка", "через", "мені", "тобі", "його", "мене", "тебе", "тепер", "зараз", "потім",
        "треба", "можна", "дуже", "трохи", "також", "тільки", "який", "яка",
        "яке", "котра", "котрий", "секунд", "секунду", "секунди", "хвилин", "хвилину", "хвилини",
        "годин", "годину", "години", "ранку", "вечора", "ночі", "один", "одна", "одну", "чотири",
        "п'ять", "шість", "вісім", "дев'ять", "десять", "двадцять", "тридцять", "сорок", "п'ятдесят",
        "сьогодні", "завтра", "післязавтра", "вчора",
    }
)

KNOWN_HALLUCINATIONS: tuple[str, ...] = (
    "дякую за перегляд",
    "дякуємо за перегляд",
    "дякую за увагу",
    "продовження слідує",
    "підписуйтесь на канал",
    "підписуйтеся на канал",
    "підписуйтесь на наш канал",
    "субтитри зроблені спільнотою amara.org",
    "спасибо за просмотр",
    "спасибо за внимание",
    "продолжение следует",
    "подписывайтесь на канал",
    "подписывайтесь на наш канал",
    "ставьте лайки",
    "субтитры сделал dimatorzok",
    "редактор субтитров",
    "thanks for watching",
    "thank you for watching",
    "please subscribe",
    "subtitles by the amara.org community",
    HINT_CONTEXT,
)

HALLUCINATION_MARKERS: tuple[str, ...] = (
    "amara org",
    "dimatorzok",
    "субтитры сделал",
    "субтитры делал",
    "субтитры создавал",
    "субтитры подготовил",
    "редактор субтитров",
    "редактор субтитрів",
    "субтитри зроблені",
    "субтитри створені",
    "субтитри підготував",
    "корректор а егорова",
    "а семкин",
)

_BRACKETED = re.compile(r"\[[^\]]*\]|\([^)]*\)|\*[^*]*\*")
_NON_WORD = re.compile(r"[^\w\s]+")
_SPACES = re.compile(r"\s+")

LOAD_ERRORS: tuple[type[Exception], ...] = (RuntimeError, OSError, ValueError, httpx.HTTPError)
DEVICE_ERRORS: tuple[type[Exception], ...] = (RuntimeError, ValueError)


class WhisperWord(Protocol):
    @property
    def word(self) -> str: ...

    @property
    def start(self) -> float: ...

    @property
    def end(self) -> float: ...

    @property
    def probability(self) -> float: ...


class WhisperSegment(Protocol):
    @property
    def text(self) -> str: ...

    @property
    def avg_logprob(self) -> float: ...

    @property
    def no_speech_prob(self) -> float: ...

    @property
    def compression_ratio(self) -> float: ...

    @property
    def words(self) -> Sequence[WhisperWord] | None: ...


def clean_text(text: str) -> str:
    lowered = _BRACKETED.sub(" ", text.lower())
    return _SPACES.sub(" ", _NON_WORD.sub(" ", lowered)).strip()


def hint_key(phrase: str) -> str:
    return " ".join(phrase.casefold().translate(_HINT_KEY_TRANSLATION).split())


def script_for(language: str) -> HintScript:
    return UKRAINIAN_SCRIPT if language == UKRAINIAN_LANGUAGE else ANY_SCRIPT


def import_whisper_model() -> Callable[..., Any]:
    try:
        from faster_whisper import WhisperModel
    except ImportError as error:
        raise ModelNotFoundError("faster-whisper не встановлено") from error
    return WhisperModel


class WhisperModelProvider:
    def __init__(
        self,
        settings: WhisperSection,
        resolve_path: Callable[[Path], Path],
        factory: Callable[..., Any] | None = None,
        retry_seconds: float = DEFAULT_RETRY_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._settings = settings
        self._resolve_path = resolve_path
        self._factory = factory
        self._retry_seconds = retry_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._loading = threading.Event()
        self._model: Any | None = None
        self._device = settings.device
        self._failure: RecognitionError | None = None
        self._failed_at = 0.0

    @property
    def device(self) -> str:
        return self._device

    @property
    def loading(self) -> bool:
        return self._loading.is_set()

    @property
    def ready(self) -> bool:
        return self._model is not None

    def model_source(self) -> str:
        candidate = self._resolve_path(Path(self._settings.model))
        if candidate.exists():
            return str(candidate)
        return self._settings.model

    def model(self) -> Any:
        with self._lock:
            if self._model is None:
                self._raise_recent_failure()
                self._model = self._load_tracked()
            return self._model

    def preload_async(self) -> threading.Thread:
        thread = threading.Thread(target=self._preload, name="whisper-preload", daemon=True)
        thread.start()
        return thread

    def fall_back_to_cpu(self) -> bool:
        with self._lock:
            if self._device == CPU_DEVICE:
                return False
            logger.warning("Whisper не працює на пристрої «%s» — перемикаюсь на процесор", self._device)
            self._device = CPU_DEVICE
            self._model = None
            self._failure = None
            return True

    def _preload(self) -> None:
        try:
            self.model()
        except RecognitionError as error:
            logger.error("Не вдалося заздалегідь завантажити Whisper: %s", error)

    def _raise_recent_failure(self) -> None:
        if self._failure is None:
            return
        if self._clock() - self._failed_at < self._retry_seconds:
            raise self._failure.with_traceback(None)
        self._failure = None

    def _load_tracked(self) -> Any:
        self._loading.set()
        try:
            return self._load()
        except RecognitionError as error:
            self._failure = error
            self._failed_at = self._clock()
            raise
        finally:
            self._loading.clear()

    def _load(self) -> Any:
        factory = self._factory or import_whisper_model()
        source = self.model_source()
        try:
            return self._create(factory, source)
        except LOAD_ERRORS as error:
            if not self._can_retry_on_cpu(error):
                raise self._load_error(source, error) from error
            logger.warning("Whisper не запустився на «%s» (%s) — пробую процесор", self._device, error)
            self._device = CPU_DEVICE
        try:
            return self._create(factory, source)
        except LOAD_ERRORS as error:
            raise self._load_error(source, error) from error

    def _create(self, factory: Callable[..., Any], source: str) -> Any:
        download_root = self._resolve_path(self._settings.download_dir)
        logger.info(
            "Завантаження моделі Whisper «%s» (%s, %s)", source, self._device, self._settings.compute_type
        )
        started = self._clock()
        model = factory(
            source,
            device=self._device,
            compute_type=self._settings.compute_type,
            download_root=str(download_root),
        )
        logger.info("Модель Whisper «%s» готова за %.1f с", source, self._clock() - started)
        return model

    def _can_retry_on_cpu(self, error: Exception) -> bool:
        return self._device != CPU_DEVICE and isinstance(error, DEVICE_ERRORS)

    def _load_error(self, source: str, error: Exception) -> RecognitionError:
        if Path(source).is_absolute():
            advice = f"Перевірте файли моделі в {source}."
        else:
            advice = "Під час першого запуску потрібен інтернет, щоб завантажити модель."
        return RecognitionError(f"Не вдалося завантажити модель Whisper «{self._settings.model}»: {error}. {advice}")


class PromptHintBuilder:
    def __init__(
        self,
        max_phrases: int,
        max_chars: int = HINT_MAX_CHARS,
        context: str = HINT_CONTEXT,
        generic_words: Iterable[str] = GENERIC_HINT_WORDS,
        common_phrases: Iterable[str] = (),
        script: HintScript = UKRAINIAN_SCRIPT,
    ) -> None:
        self._max_phrases = max_phrases
        self._max_chars = max_chars
        self._context = context
        self._generic = frozenset(hint_key(word) for word in generic_words)
        self._common = frozenset(hint_key(phrase) for phrase in common_phrases)
        self._script = script

    @classmethod
    def for_settings(cls, settings: WhisperSection, common_phrases: Iterable[str] = ()) -> PromptHintBuilder:
        return cls(settings.hint_phrases, common_phrases=common_phrases, script=script_for(settings.language))

    def build(self, grammar: Iterable[str] | None) -> str:
        chosen: list[str] = []
        covered: set[str] = set()
        budget = self._max_chars - len(self._context)
        for key, phrase in self._candidates(grammar or ()):
            if len(chosen) >= self._max_phrases:
                break
            cost = len(phrase) + HINT_SEPARATOR_COST
            if cost > budget or key in covered:
                continue
            chosen.append(phrase)
            covered.update(key.split())
            budget -= cost
        if not chosen:
            return self._context
        return f"{self._context} {', '.join(chosen)}."

    def _candidates(self, grammar: Iterable[str]) -> list[tuple[str, str]]:
        unique: dict[str, str] = {}
        for raw in grammar:
            phrase = " ".join(raw.split())
            key = hint_key(phrase)
            if key and "[" not in phrase and self._script.accepts(key):
                unique.setdefault(key, phrase)
        tiers: tuple[list[tuple[str, str]], ...] = ([], [], [], [])
        for key, phrase in unique.items():
            tier = self._tier(key)
            if tier is not None:
                tiers[tier].append((key, phrase))
        return [item for tier in tiers for item in tier]

    def _tier(self, key: str) -> int | None:
        common = key in self._common
        if " " in key:
            return COMMON_PHRASE_TIER if common else SPECIFIC_PHRASE_TIER
        if not self._is_distinctive(key):
            return None
        return COMMON_WORD_TIER if common else SPECIFIC_WORD_TIER

    def _is_distinctive(self, word: str) -> bool:
        return len(word) >= HINT_MIN_WORD_LENGTH and word not in self._generic and not word.isdigit()


class HallucinationGuard:
    def __init__(
        self,
        phrases: Iterable[str] = KNOWN_HALLUCINATIONS,
        markers: Iterable[str] = HALLUCINATION_MARKERS,
        no_speech_threshold: float = 0.6,
        logprob_threshold: float = -1.0,
        compression_threshold: float = 2.4,
    ) -> None:
        cleaned = sorted({clean_text(phrase) for phrase in phrases} - {""}, key=len, reverse=True)
        alternation = "|".join(re.escape(phrase) for phrase in cleaned)
        self._pattern = re.compile(rf"\b(?:{alternation})\b") if cleaned else None
        self._markers = tuple(marker for marker in (clean_text(item) for item in markers) if marker)
        self._no_speech_threshold = no_speech_threshold
        self._logprob_threshold = logprob_threshold
        self._compression_threshold = compression_threshold

    def keep_segment(self, segment: WhisperSegment) -> bool:
        silent = segment.no_speech_prob > self._no_speech_threshold and segment.avg_logprob < self._logprob_threshold
        looping = segment.compression_ratio > self._compression_threshold
        return not silent and not looping

    def is_hallucination(self, text: str) -> bool:
        cleaned = clean_text(text)
        if not cleaned:
            return True
        if any(marker in cleaned for marker in self._markers):
            return True
        if self._pattern is None:
            return False
        return not self._pattern.sub(" ", cleaned).strip()


class WhisperTranscriber:
    def __init__(
        self,
        provider: WhisperModelProvider,
        settings: WhisperSection,
        preprocessor: AudioPreprocessor | None,
        fallback: Transcriber | None = None,
        sample_rate: int = WHISPER_SAMPLE_RATE,
        min_word_confidence: float = 0.4,
        hints: PromptHintBuilder | None = None,
        guard: HallucinationGuard | None = None,
    ) -> None:
        self._provider = provider
        self._settings = settings
        self._preprocessor = preprocessor
        self._fallback = fallback
        self._sample_rate = sample_rate
        self._min_word_confidence = min_word_confidence
        self._hints = hints or PromptHintBuilder.for_settings(settings)
        self._guard = guard or HallucinationGuard()
        self._fallback_announced = False

    def transcribe(
        self,
        pcm: bytes,
        language: str | None = None,
        grammar: Sequence[str] | None = None,
        alternatives: int = 0,
    ) -> Transcript:
        target = self._language(language)
        label = target or FALLBACK_LANGUAGE
        audio = self._prepare(pcm)
        if audio.size == 0:
            return Transcript(text="", language=label)
        segments, detected = self._decode(audio, target, self._hints.build(grammar))
        return self._build(segments, detected or label)

    def transcribe_command(self, pcm: bytes, grammar: Sequence[str] | None) -> Transcript:
        if self._fallback is not None and self._provider.loading:
            logger.info("Модель Whisper ще завантажується — використовую резервне розпізнавання")
            return self._fallback.transcribe_command(pcm, grammar)
        try:
            transcript = self.transcribe(pcm, grammar=grammar)
        except RecognitionError as error:
            if self._fallback is None:
                raise
            self._announce_fallback(error)
            return self._fallback.transcribe_command(pcm, grammar)
        if transcript.is_empty and self._fallback is not None:
            return self._fallback_for_empty(self._fallback, pcm, grammar, transcript)
        return transcript

    def is_reliable(self, transcript: Transcript) -> bool:
        if transcript.is_empty:
            return False
        return transcript.confidence >= self._min_word_confidence

    def _language(self, language: str | None) -> str | None:
        value = (language or self._settings.language).strip()
        if not value or value == AUTO_LANGUAGE:
            return None
        return value

    def _prepare(self, pcm: bytes) -> np.ndarray:
        processed = self._preprocessor.process(pcm) if self._preprocessor is not None else pcm
        return resample(pcm_to_float32(processed), self._sample_rate, WHISPER_SAMPLE_RATE)

    def _decode(self, audio: np.ndarray, language: str | None, prompt: str) -> tuple[list[WhisperSegment], str | None]:
        model = self._provider.model()
        try:
            segments, info = model.transcribe(
                audio,
                language=language,
                beam_size=self._settings.beam_size,
                vad_filter=self._settings.vad_filter,
                word_timestamps=True,
                condition_on_previous_text=False,
                initial_prompt=prompt,
                temperature=DECODING_TEMPERATURE,
            )
            return list(segments), info.language
        except ValueError as error:
            raise RecognitionError(f"Whisper не зміг розпізнати мовлення: {error}") from error
        except RuntimeError as error:
            if not self._provider.fall_back_to_cpu():
                raise RecognitionError(f"Whisper не зміг розпізнати мовлення: {error}") from error
            logger.warning("Повторюю розпізнавання Whisper на процесорі після помилки: %s", error)
        return self._decode(audio, language, prompt)

    def _build(self, segments: Iterable[WhisperSegment], language: str) -> Transcript:
        kept = [segment for segment in segments if self._guard.keep_segment(segment)]
        text = " ".join(piece for piece in (segment.text.strip() for segment in kept) if piece)
        if self._guard.is_hallucination(text):
            if text:
                logger.info("Відкинуто ймовірну галюцинацію Whisper: «%s»", text)
            return Transcript(text="", language=language)
        words = tuple(self._word(word) for segment in kept for word in segment.words or () if word.word.strip())
        return Transcript(text=text, words=words, language=language)

    @staticmethod
    def _fallback_for_empty(
        fallback: Transcriber, pcm: bytes, grammar: Sequence[str] | None, empty: Transcript
    ) -> Transcript:
        try:
            return fallback.transcribe_command(pcm, grammar)
        except RecognitionError as error:
            logger.warning("Резервне розпізнавання недоступне: %s", error)
            return empty

    def _announce_fallback(self, error: RecognitionError) -> None:
        if self._fallback_announced:
            logger.debug("Whisper недоступний, резервне розпізнавання: %s", error)
            return
        self._fallback_announced = True
        logger.warning("Whisper недоступний (%s) — використовую резервне розпізнавання", error)

    @staticmethod
    def _word(word: WhisperWord) -> RecognizedWord:
        return RecognizedWord(
            text=word.word.strip(),
            start=float(word.start),
            end=float(word.end),
            confidence=float(word.probability),
        )
