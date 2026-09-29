from __future__ import annotations

import logging
import sys
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from jarvis.core.config import WhisperSection
from jarvis.core.errors import ModelNotFoundError, RecognitionError
from jarvis.core.speech_types import RecognizedWord, Transcript
from jarvis.speech.audio_preprocess import AudioPreprocessor, float_to_pcm, pcm_to_float32
from jarvis.speech.recognizer_vosk import SpeechTranscriber
from jarvis.speech.transcriber import Transcriber
from jarvis.speech.whisper_engine import (
    HINT_CONTEXT,
    HINT_MAX_CHARS,
    HallucinationGuard,
    PromptHintBuilder,
    WhisperModelProvider,
    WhisperTranscriber,
)

SAMPLE_RATE = 16000


@dataclass
class FakeWord:
    word: str
    start: float
    end: float
    probability: float


@dataclass
class FakeSegment:
    text: str
    words: list[FakeWord] | None = None
    avg_logprob: float = -0.2
    no_speech_prob: float = 0.05
    compression_ratio: float = 1.3


@dataclass(frozen=True)
class FakeInfo:
    language: str


@dataclass
class FakeModel:
    segments: Sequence[FakeSegment] = ()
    language: str = "uk"
    error: Exception | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)

    def transcribe(self, audio: np.ndarray, **options: Any) -> tuple[Iterator[FakeSegment], FakeInfo]:
        self.calls.append({"audio": audio, **options})
        if self.error is not None:
            raise self.error
        return iter(self.segments), FakeInfo(options.get("language") or self.language)


class FakeFactory:
    def __init__(self, *outcomes: Any, delay: float = 0.0, gate: threading.Event | None = None) -> None:
        self._outcomes = list(outcomes)
        self._delay = delay
        self._gate = gate
        self._lock = threading.Lock()
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, source: str, **kwargs: Any) -> Any:
        with self._lock:
            self.calls.append((source, kwargs))
            outcome = self._outcomes.pop(0) if len(self._outcomes) > 1 else self._outcomes[0]
        if self._gate is not None:
            self._gate.wait(5)
        time.sleep(self._delay)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeFallback:
    def __init__(self, text: str = "резервний текст", error: Exception | None = None) -> None:
        self._text = text
        self._error = error
        self.calls: list[tuple[bytes, Sequence[str] | None]] = []

    def transcribe(
        self,
        pcm: bytes,
        language: str | None = None,
        grammar: Sequence[str] | None = None,
        alternatives: int = 0,
    ) -> Transcript:
        return Transcript(text=self._text)

    def transcribe_command(self, pcm: bytes, grammar: Sequence[str] | None) -> Transcript:
        self.calls.append((pcm, grammar))
        if self._error is not None:
            raise self._error
        return Transcript(text=self._text)

    def is_reliable(self, transcript: Transcript) -> bool:
        return not transcript.is_empty


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def tone(seconds: float = 0.5, amplitude: float = 0.3, frequency: float = 1000.0, offset: float = 0.0) -> bytes:
    moments = np.arange(int(SAMPLE_RATE * seconds)) / SAMPLE_RATE
    return float_to_pcm(amplitude * np.sin(2 * np.pi * frequency * moments) + offset)


def settings(**overrides: Any) -> WhisperSection:
    return WhisperSection(**overrides)


def resolver(base: Path) -> Callable[[Path], Path]:
    def resolve(path: Path) -> Path:
        return path if path.is_absolute() else base / path

    return resolve


def build(
    tmp_path: Path,
    model: FakeModel | None = None,
    fallback: Transcriber | None = None,
    preprocessor: AudioPreprocessor | None = None,
    sample_rate: int = SAMPLE_RATE,
    **overrides: Any,
) -> tuple[WhisperTranscriber, FakeFactory, FakeModel]:
    fake_model = model or FakeModel()
    factory = FakeFactory(fake_model)
    config = settings(**overrides)
    provider = WhisperModelProvider(config, resolver(tmp_path), factory)
    transcriber = WhisperTranscriber(provider, config, preprocessor, fallback, sample_rate=sample_rate)
    return transcriber, factory, fake_model


def segment(text: str, *words: tuple[str, float], **metrics: float) -> FakeSegment:
    fake_words = [FakeWord(word, index * 0.4, index * 0.4 + 0.3, probability) for index, (word, probability) in enumerate(words)]
    return FakeSegment(text=text, words=fake_words, **metrics)


def test_transcribe_passes_expected_decoding_options(tmp_path: Path) -> None:
    transcriber, _, model = build(tmp_path, FakeModel([segment(" Відкрий хром", (" Відкрий", 0.9), (" хром", 0.8))]))

    transcriber.transcribe(tone(), grammar=["відкрий дискорд", "хром"])

    options = model.calls[0]
    assert options["language"] == "uk"
    assert options["beam_size"] == 5
    assert options["vad_filter"] is True
    assert options["word_timestamps"] is True
    assert options["condition_on_previous_text"] is False
    assert options["temperature"] == 0.0
    assert options["initial_prompt"] == f"{HINT_CONTEXT} відкрий дискорд, хром."
    assert options["audio"].dtype == np.float32


def test_language_argument_overrides_settings(tmp_path: Path) -> None:
    transcriber, _, model = build(tmp_path, FakeModel([segment("привет", ("привет", 0.9))]))

    transcript = transcriber.transcribe(tone(), language="ru")

    assert model.calls[0]["language"] == "ru"
    assert transcript.language == "ru"


def test_auto_language_lets_whisper_detect(tmp_path: Path) -> None:
    transcriber, _, model = build(tmp_path, FakeModel([segment("hello", ("hello", 0.9))], language="en"), language="auto")

    transcript = transcriber.transcribe(tone())

    assert model.calls[0]["language"] is None
    assert transcript.language == "en"


def test_settings_are_forwarded_to_decoder(tmp_path: Path) -> None:
    transcriber, _, model = build(tmp_path, FakeModel([segment("так", ("так", 0.9))]), beam_size=2, vad_filter=False)

    transcriber.transcribe(tone())

    assert model.calls[0]["beam_size"] == 2
    assert model.calls[0]["vad_filter"] is False


def test_transcript_maps_segments_and_words(tmp_path: Path) -> None:
    segments = [
        segment(" Відкрий Діскорд.", (" Відкрий", 0.91), (" Діскорд.", 0.62)),
        segment(" Будь ласка", (" Будь", 0.8), (" ", 0.1), (" ласка", 0.7)),
    ]
    transcriber, _, _ = build(tmp_path, FakeModel(segments))

    transcript = transcriber.transcribe(tone())

    assert transcript.text == "Відкрий Діскорд. Будь ласка"
    assert [word.text for word in transcript.words] == ["Відкрий", "Діскорд.", "Будь", "ласка"]
    assert transcript.words[1] == RecognizedWord(text="Діскорд.", start=0.4, end=0.7, confidence=0.62)
    assert transcript.confidence == pytest.approx((0.91 + 0.62 + 0.8 + 0.7) / 4)
    assert transcript.language == "uk"
    assert transcript.alternatives == ()


def test_alternatives_are_ignored(tmp_path: Path) -> None:
    transcriber, _, _ = build(tmp_path, FakeModel([segment("пауза", ("пауза", 0.9))]))

    assert transcriber.transcribe(tone(), alternatives=5).alternatives == ()


def test_segment_without_words_keeps_text(tmp_path: Path) -> None:
    transcriber, _, _ = build(tmp_path, FakeModel([FakeSegment(text="стоп", words=None)]))

    transcript = transcriber.transcribe(tone())

    assert transcript.text == "стоп"
    assert transcript.words == ()


def test_empty_audio_does_not_load_model(tmp_path: Path) -> None:
    transcriber, factory, _ = build(tmp_path)

    transcript = transcriber.transcribe(b"")

    assert transcript.is_empty
    assert factory.calls == []


def test_silent_segment_is_dropped_by_no_speech_rule(tmp_path: Path) -> None:
    segments = [
        segment("шум", ("шум", 0.3), no_speech_prob=0.9, avg_logprob=-1.4),
        segment("увімкни музику", ("увімкни", 0.9), ("музику", 0.9)),
    ]
    transcriber, _, _ = build(tmp_path, FakeModel(segments))

    transcript = transcriber.transcribe(tone())

    assert transcript.text == "увімкни музику"
    assert [word.text for word in transcript.words] == ["увімкни", "музику"]


def test_no_speech_rule_requires_both_conditions(tmp_path: Path) -> None:
    segments = [segment("тихо", ("тихо", 0.8), no_speech_prob=0.9, avg_logprob=-0.3)]
    transcriber, _, _ = build(tmp_path, FakeModel(segments))

    assert transcriber.transcribe(tone()).text == "тихо"


def test_repetition_loop_segment_is_dropped(tmp_path: Path) -> None:
    segments = [segment("так так так так так так так так", ("так", 0.5), compression_ratio=3.1)]
    transcriber, _, _ = build(tmp_path, FakeModel(segments))

    assert transcriber.transcribe(tone()).is_empty


@pytest.mark.parametrize(
    "text",
    [
        "Дякую за перегляд!",
        "Дякуємо за перегляд.",
        "Продовження слідує...",
        "Субтитри зроблені спільнотою Amara.org",
        "Субтитры сделал DimaTorzok",
        "Редактор субтитров А.Семкин Корректор А.Егорова",
        "Спасибо за просмотр! Подписывайтесь на канал!",
        "Продолжение следует...",
        "Thanks for watching!",
        "Thank you for watching.",
        "...",
        " … ",
        "(Музика)",
        "[музыка]",
        "Голосові команди асистенту Джарвіс:",
    ],
)
def test_known_hallucinations_become_empty(tmp_path: Path, text: str) -> None:
    transcriber, _, _ = build(tmp_path, FakeModel([segment(text, (text, 0.9))]))

    transcript = transcriber.transcribe(tone())

    assert transcript.is_empty
    assert transcript.words == ()


@pytest.mark.parametrize("text", ["Дякую, Джарвіс", "Увімкни субтитри", "Продовж відтворення", "Дякую"])
def test_real_commands_are_not_mistaken_for_hallucinations(text: str) -> None:
    assert not HallucinationGuard().is_hallucination(text)


def test_hint_prefers_multi_word_and_distinctive_words() -> None:
    builder = PromptHintBuilder(max_phrases=10)

    hint = builder.build(["на", "через", "хром", "відкрий дискорд", "дискорд", "25", "[unk]", "увімкни   музику", "Хром"])

    assert hint == f"{HINT_CONTEXT} відкрий дискорд, увімкни музику, хром."


def test_hint_puts_user_specific_phrases_before_common_commands() -> None:
    common = ["вимкни звук", "котра година", "увімкни", "будь-ласка"]
    builder = PromptHintBuilder(max_phrases=10, common_phrases=common)

    hint = builder.build(["будь ласка", "вимкни звук", "котра година", "увімкни", "діскорд", "мій проєкт"])

    assert hint == f"{HINT_CONTEXT} мій проєкт, діскорд, будь ласка, вимкни звук, котра година, увімкни."


def test_hint_skips_foreign_script_for_ukrainian() -> None:
    builder = PromptHintBuilder.for_settings(settings(language="uk"))

    hint = builder.build(["what time", "выключи звук", "съешь", "вимкни звук", "google chrome", "п’ятниця"])

    assert hint == f"{HINT_CONTEXT} вимкни звук, п’ятниця."


def test_hint_keeps_any_script_for_other_languages() -> None:
    builder = PromptHintBuilder.for_settings(settings(language="en"))

    assert builder.build(["what time", "google chrome"]) == f"{HINT_CONTEXT} what time, google chrome."


def test_transcriber_can_use_injected_hint_builder(tmp_path: Path) -> None:
    config = settings()
    model = FakeModel([segment("так", ("так", 0.9))])
    provider = WhisperModelProvider(config, resolver(tmp_path), FakeFactory(model))
    hints = PromptHintBuilder.for_settings(config, common_phrases=["вимкни звук"])
    transcriber = WhisperTranscriber(provider, config, None, hints=hints)

    transcriber.transcribe(tone(), grammar=["вимкни звук", "запусти стім"])

    assert model.calls[0]["initial_prompt"] == f"{HINT_CONTEXT} запусти стім, вимкни звук."


def test_hint_for_empty_grammar_is_context_only() -> None:
    builder = PromptHintBuilder(max_phrases=10)

    assert builder.build(None) == HINT_CONTEXT
    assert builder.build([]) == HINT_CONTEXT


def test_hint_respects_phrase_limit(tmp_path: Path) -> None:
    grammar = [f"команда номер {index}" for index in range(20)]
    transcriber, _, model = build(tmp_path, FakeModel([segment("так", ("так", 0.9))]), hint_phrases=3)

    transcriber.transcribe(tone(), grammar=grammar)

    assert model.calls[0]["initial_prompt"] == f"{HINT_CONTEXT} команда номер 0, команда номер 1, команда номер 2."


def test_hint_respects_character_limit(tmp_path: Path) -> None:
    grammar = [f"дуже довга голосова команда для програми номер {index}" for index in range(200)]
    transcriber, _, model = build(tmp_path, FakeModel([segment("так", ("так", 0.9))]), hint_phrases=500)

    transcriber.transcribe(tone(), grammar=grammar)

    prompt = model.calls[0]["initial_prompt"]
    assert prompt.startswith(HINT_CONTEXT)
    assert len(prompt) <= HINT_MAX_CHARS
    assert len(prompt) > HINT_MAX_CHARS - 60


def test_hint_skips_phrase_that_does_not_fit_but_keeps_shorter_ones() -> None:
    builder = PromptHintBuilder(max_phrases=5, max_chars=len(HINT_CONTEXT) + 20)

    hint = builder.build(["надзвичайно довга фраза яка не влазить", "відкрий хром"])

    assert hint == f"{HINT_CONTEXT} відкрий хром."


def test_command_uses_fallback_when_provider_fails(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    fallback = FakeFallback()
    config = settings()
    provider = WhisperModelProvider(config, resolver(tmp_path), FakeFactory(OSError("мережа недоступна")))
    transcriber = WhisperTranscriber(provider, config, None, fallback)

    with caplog.at_level(logging.WARNING, logger="jarvis.speech.whisper_engine"):
        first = transcriber.transcribe_command(tone(), ["відкрий хром"])
        second = transcriber.transcribe_command(tone(), ["відкрий хром"])

    assert first.text == second.text == "резервний текст"
    assert len(fallback.calls) == 2
    assert fallback.calls[0][1] == ["відкрий хром"]
    warnings = [record for record in caplog.records if "резервне розпізнавання" in record.getMessage()]
    assert len(warnings) == 1


def test_command_uses_fallback_when_faster_whisper_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    fallback = FakeFallback()
    config = settings()
    provider = WhisperModelProvider(config, resolver(tmp_path))
    transcriber = WhisperTranscriber(provider, config, None, fallback)

    with pytest.raises(ModelNotFoundError, match="faster-whisper не встановлено"):
        provider.model()
    assert transcriber.transcribe_command(tone(), None).text == "резервний текст"


def test_command_without_fallback_reraises(tmp_path: Path) -> None:
    config = settings()
    provider = WhisperModelProvider(config, resolver(tmp_path), FakeFactory(OSError("offline")))
    transcriber = WhisperTranscriber(provider, config, None)

    with pytest.raises(RecognitionError):
        transcriber.transcribe_command(tone(), None)


def test_command_uses_fallback_when_whisper_hears_nothing(tmp_path: Path) -> None:
    fallback = FakeFallback("відкрий хром")
    transcriber, _, _ = build(tmp_path, FakeModel([segment("Дякую за перегляд!", ("Дякую", 0.9))]), fallback=fallback)

    assert transcriber.transcribe_command(tone(), None).text == "відкрий хром"
    assert len(fallback.calls) == 1


def test_command_keeps_empty_result_when_fallback_fails(tmp_path: Path) -> None:
    fallback = FakeFallback(error=ModelNotFoundError("немає моделі"))
    transcriber, _, _ = build(tmp_path, FakeModel([]), fallback=fallback)

    assert transcriber.transcribe_command(tone(), None).is_empty


def test_command_prefers_whisper_when_it_succeeds(tmp_path: Path) -> None:
    fallback = FakeFallback()
    transcriber, _, _ = build(tmp_path, FakeModel([segment("котра година", ("котра", 0.9), ("година", 0.9))]), fallback=fallback)

    assert transcriber.transcribe_command(tone(), None).text == "котра година"
    assert fallback.calls == []


def test_command_uses_fallback_while_model_is_loading(tmp_path: Path) -> None:
    gate = threading.Event()
    fallback = FakeFallback()
    config = settings()
    provider = WhisperModelProvider(config, resolver(tmp_path), FakeFactory(FakeModel(), gate=gate))
    transcriber = WhisperTranscriber(provider, config, None, fallback)

    thread = provider.preload_async()
    deadline = time.monotonic() + 5
    while not provider.loading and time.monotonic() < deadline:
        time.sleep(0.005)
    result = transcriber.transcribe_command(tone(), None)
    gate.set()
    thread.join(5)

    assert result.text == "резервний текст"
    assert provider.ready
    assert not provider.loading


def test_provider_loads_model_once_across_threads(tmp_path: Path) -> None:
    model = FakeModel()
    factory = FakeFactory(model, delay=0.05)
    provider = WhisperModelProvider(settings(), resolver(tmp_path), factory)
    results: list[Any] = []
    barrier = threading.Barrier(8)

    def worker() -> None:
        barrier.wait()
        results.append(provider.model())

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)

    assert len(factory.calls) == 1
    assert len(results) == 8
    assert all(result is model for result in results)


def test_provider_is_lazy(tmp_path: Path) -> None:
    factory = FakeFactory(FakeModel())

    provider = WhisperModelProvider(settings(), resolver(tmp_path), factory)

    assert factory.calls == []
    assert not provider.ready


def test_provider_loads_existing_local_path(tmp_path: Path) -> None:
    local = tmp_path / "models" / "whisper-uk"
    local.mkdir(parents=True)
    factory = FakeFactory(FakeModel())
    provider = WhisperModelProvider(
        settings(model="models/whisper-uk", device="cpu", compute_type="int8"), resolver(tmp_path), factory
    )

    provider.model()

    source, kwargs = factory.calls[0]
    assert source == str(local)
    assert kwargs == {
        "device": "cpu",
        "compute_type": "int8",
        "download_root": str(tmp_path / "models" / "whisper"),
    }


def test_provider_treats_missing_path_as_model_size(tmp_path: Path) -> None:
    factory = FakeFactory(FakeModel())
    provider = WhisperModelProvider(
        settings(model="large-v3-turbo", download_dir=Path("cache/whisper")), resolver(tmp_path), factory
    )

    provider.model()

    source, kwargs = factory.calls[0]
    assert source == "large-v3-turbo"
    assert kwargs["download_root"] == str(tmp_path / "cache" / "whisper")
    assert kwargs["device"] == "auto"


def test_provider_wraps_load_errors_with_helpful_message(tmp_path: Path) -> None:
    provider = WhisperModelProvider(settings(model="medium"), resolver(tmp_path), FakeFactory(OSError("connection refused")))

    with pytest.raises(RecognitionError) as caught:
        provider.model()

    message = str(caught.value)
    assert "medium" in message
    assert "інтернет" in message
    assert not isinstance(caught.value, ModelNotFoundError)


def test_provider_retries_on_cpu_when_gpu_load_fails(tmp_path: Path) -> None:
    model = FakeModel()
    factory = FakeFactory(RuntimeError("CUDA driver version is insufficient"), model)
    provider = WhisperModelProvider(settings(device="cuda"), resolver(tmp_path), factory)

    assert provider.model() is model
    assert [kwargs["device"] for _, kwargs in factory.calls] == ["cuda", "cpu"]
    assert provider.device == "cpu"


def test_provider_does_not_retry_network_errors_on_cpu(tmp_path: Path) -> None:
    factory = FakeFactory(OSError("offline"))
    provider = WhisperModelProvider(settings(device="cuda"), resolver(tmp_path), factory)

    with pytest.raises(RecognitionError):
        provider.model()
    assert len(factory.calls) == 1


def test_provider_waits_before_retrying_failed_load(tmp_path: Path) -> None:
    clock = FakeClock()
    model = FakeModel()
    factory = FakeFactory(OSError("offline"), model)
    provider = WhisperModelProvider(settings(), resolver(tmp_path), factory, retry_seconds=30.0, clock=clock)

    with pytest.raises(RecognitionError):
        provider.model()
    with pytest.raises(RecognitionError):
        provider.model()
    assert len(factory.calls) == 1

    clock.now += 31.0

    assert provider.model() is model
    assert len(factory.calls) == 2


def test_preload_async_logs_errors(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    provider = WhisperModelProvider(settings(), resolver(tmp_path), FakeFactory(ValueError("bad model")))

    with caplog.at_level(logging.ERROR, logger="jarvis.speech.whisper_engine"):
        thread = provider.preload_async()
        thread.join(5)

    assert thread.daemon
    assert not provider.ready
    assert any("Whisper" in record.getMessage() for record in caplog.records)


def test_runtime_error_during_decoding_retries_on_cpu(tmp_path: Path) -> None:
    broken = FakeModel(error=RuntimeError("Library cublas64_12.dll is not found"))
    healthy = FakeModel([segment("гучніше", ("гучніше", 0.9))])
    factory = FakeFactory(broken, healthy)
    config = settings(device="auto")
    provider = WhisperModelProvider(config, resolver(tmp_path), factory)
    transcriber = WhisperTranscriber(provider, config, None)

    assert transcriber.transcribe(tone()).text == "гучніше"
    assert [kwargs["device"] for _, kwargs in factory.calls] == ["auto", "cpu"]


def test_runtime_error_on_cpu_becomes_recognition_error(tmp_path: Path) -> None:
    transcriber, _, _ = build(tmp_path, FakeModel(error=RuntimeError("boom")), device="cpu")

    with pytest.raises(RecognitionError, match="boom"):
        transcriber.transcribe(tone())


def test_invalid_language_becomes_recognition_error(tmp_path: Path) -> None:
    transcriber, _, _ = build(tmp_path, FakeModel(error=ValueError("'ua' is not a valid language code")))

    with pytest.raises(RecognitionError):
        transcriber.transcribe(tone(), language="ua")


@pytest.mark.parametrize(
    ("confidences", "expected"),
    [((0.9, 0.8), True), ((0.3, 0.35), False), ((0.4,), True)],
)
def test_is_reliable_uses_mean_word_confidence(tmp_path: Path, confidences: tuple[float, ...], expected: bool) -> None:
    transcriber, _, _ = build(tmp_path)
    words = tuple(RecognizedWord(text=f"w{index}", start=0.0, end=0.1, confidence=value) for index, value in enumerate(confidences))

    assert transcriber.is_reliable(Transcript(text="щось", words=words)) is expected


def test_is_reliable_rejects_empty_transcript(tmp_path: Path) -> None:
    transcriber, _, _ = build(tmp_path)

    assert not transcriber.is_reliable(Transcript(text=""))


def test_transcriber_applies_preprocessor(tmp_path: Path) -> None:
    preprocessor = AudioPreprocessor(SAMPLE_RATE, target_peak=0.7)
    transcriber, _, model = build(tmp_path, FakeModel([segment("так", ("так", 0.9))]), preprocessor=preprocessor)

    transcriber.transcribe(tone(amplitude=0.2))

    audio = model.calls[0]["audio"]
    assert float(np.max(np.abs(audio))) == pytest.approx(0.7, abs=0.01)


def test_transcriber_resamples_to_whisper_rate(tmp_path: Path) -> None:
    transcriber, _, model = build(tmp_path, FakeModel([segment("так", ("так", 0.9))]), sample_rate=8000)

    transcriber.transcribe(float_to_pcm(np.zeros(8000)))

    assert model.calls[0]["audio"].shape == (16000,)
    assert model.calls[0]["audio"].dtype == np.float32


def test_both_engines_satisfy_transcriber_protocol(tmp_path: Path) -> None:
    transcriber, _, _ = build(tmp_path)

    assert isinstance(transcriber, Transcriber)
    assert issubclass(SpeechTranscriber, Transcriber)


def test_preprocessor_removes_dc_offset() -> None:
    preprocessor = AudioPreprocessor(SAMPLE_RATE)

    output = pcm_to_float32(preprocessor.process(tone(amplitude=0.2, offset=0.3)))

    assert abs(float(np.mean(output))) < 0.01
    assert float(np.max(np.abs(output))) == pytest.approx(0.7, abs=0.01)


def test_preprocessor_caps_gain() -> None:
    unfiltered = AudioPreprocessor(SAMPLE_RATE, target_peak=0.7, max_gain=8.0, highpass_hz=0.0)
    filtered = AudioPreprocessor(SAMPLE_RATE, target_peak=0.7, max_gain=8.0)

    exact = pcm_to_float32(unfiltered.process(tone(amplitude=0.01)))
    shaped = pcm_to_float32(filtered.process(tone(amplitude=0.01)))

    assert float(np.max(np.abs(exact))) == pytest.approx(0.08, abs=0.001)
    assert float(np.max(np.abs(shaped))) < 0.1


def test_preprocessor_never_clips() -> None:
    preprocessor = AudioPreprocessor(SAMPLE_RATE, target_peak=1.5, max_gain=50.0)
    square = np.where(np.sin(2 * np.pi * 200 * np.arange(SAMPLE_RATE // 2) / SAMPLE_RATE) >= 0, 0.99, -0.99)

    samples = np.frombuffer(preprocessor.process(float_to_pcm(square)), dtype="<i2").astype(np.int32)

    assert samples.max() <= 32767
    assert samples.min() >= -32768
    assert np.count_nonzero(np.abs(samples) >= 32767) < len(samples) // 100


def test_preprocessor_attenuates_loud_audio_to_target() -> None:
    preprocessor = AudioPreprocessor(SAMPLE_RATE, target_peak=0.5)

    output = pcm_to_float32(preprocessor.process(tone(amplitude=0.95)))

    assert float(np.max(np.abs(output))) == pytest.approx(0.5, abs=0.01)


@pytest.mark.parametrize("offset", [0.0, 0.25])
def test_preprocessor_keeps_silence_silent(offset: float) -> None:
    preprocessor = AudioPreprocessor(SAMPLE_RATE)
    silence = float_to_pcm(np.full(SAMPLE_RATE // 4, offset))

    output = np.frombuffer(preprocessor.process(silence), dtype="<i2")

    assert len(output) == SAMPLE_RATE // 4
    assert int(np.max(np.abs(output))) <= 1


def test_preprocessor_handles_empty_input() -> None:
    preprocessor = AudioPreprocessor(SAMPLE_RATE)

    assert preprocessor.process(b"") == b""
    assert preprocessor.to_float32(b"").size == 0


def test_preprocessor_keeps_length_and_drops_trailing_odd_byte() -> None:
    preprocessor = AudioPreprocessor(SAMPLE_RATE)
    pcm = tone(seconds=0.1)

    assert len(preprocessor.process(pcm)) == len(pcm)
    assert len(preprocessor.process(pcm + b"\x01")) == len(pcm)


def test_to_float32_scales_into_unit_range() -> None:
    preprocessor = AudioPreprocessor(SAMPLE_RATE)
    pcm = np.array([-32768, 0, 16384, 32767], dtype="<i2").tobytes()

    audio = preprocessor.to_float32(pcm)

    assert audio.dtype == np.float32
    assert audio.tolist() == pytest.approx([-1.0, 0.0, 0.5, 32767 / 32768])


def test_preprocessor_without_highpass_still_normalises() -> None:
    preprocessor = AudioPreprocessor(SAMPLE_RATE, highpass_hz=0.0)

    output = pcm_to_float32(preprocessor.process(tone(amplitude=0.2)))

    assert float(np.max(np.abs(output))) == pytest.approx(0.7, abs=0.01)
