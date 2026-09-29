from __future__ import annotations

import logging
import queue
import threading
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

from jarvis.core.config import TrainingSection
from jarvis.core.errors import (
    AudioDeviceError,
    EmptyRecordingError,
    JarvisError,
    NotEnoughSamplesError,
    RecognitionError,
    TrainingError,
)
from jarvis.core.event_bus import EventBus
from jarvis.core.events import (
    BindingsChanged,
    Event,
    ListenerPauseRequested,
    MicLevelChanged,
    ShutdownRequested,
    TrainingFailed,
    TrainingFinishRequested,
    TrainingModelBuilt,
    TrainingRecordingStarted,
    TrainingSampleDeleteRequested,
    TrainingSampleRequested,
    TrainingSamplesChanged,
    TrainingSaved,
    TrainingSaveRequested,
    TrainingSessionClosed,
    TrainingSessionStarted,
    TrainingStartRequested,
    TrainingTestRequested,
    TrainingTestResult,
    VocabularyChanged,
    VocabularyWordAddRequested,
)
from jarvis.core.intent import Action
from jarvis.core.models import AliasSource, Binding, BindingSource, VocabularyWord, VoiceSample
from jarvis.nlu.pronunciation_matcher import PronunciationScorer
from jarvis.nlu.text_normalizer import TextNormalizer
from jarvis.speech.audio_io import MicrophoneStream, RecordingLimits, UtteranceRecorder, WavFile
from jarvis.speech.recognizer_vosk import UNKNOWN_TOKEN, SpeechTranscriber
from jarvis.storage.repositories.bindings import BindingRepository
from jarvis.storage.repositories.vocabulary import VocabularyRepository
from jarvis.training.voice_templates import (
    AcousticModel,
    AcousticModelBuilder,
    FeatureExtractor,
    FloatArray,
    deserialize_features,
    serialize_features,
)

logger = logging.getLogger(__name__)

PAUSE_REASON = "training"
START_TIMEOUT_SECONDS = 6.0
_STOP = object()
Job = Callable[[], None]


@dataclass(frozen=True)
class _TrainingJob:
    word_id: int | None
    run: Job


@dataclass(frozen=True)
class RecordedSample:
    pcm: bytes
    transcripts: tuple[str, ...]


class SampleTranscriber:
    def __init__(self, transcriber: SpeechTranscriber, languages: Iterable[str], alternatives: int) -> None:
        self._transcriber = transcriber
        self._languages = tuple(dict.fromkeys(languages))
        self._alternatives = alternatives

    def transcripts(self, pcm: bytes) -> tuple[str, ...]:
        collected: list[str] = []
        for language in self._languages:
            try:
                transcript = self._transcriber.transcribe(pcm, language, alternatives=self._alternatives)
            except RecognitionError as error:
                logger.warning("Модель %s не змогла розпізнати зразок: %s", language, error)
                continue
            collected.extend([transcript.text, *transcript.alternatives])
        cleaned = (TextNormalizer.basic(item.replace(UNKNOWN_TOKEN, " ")) for item in collected)
        return tuple(dict.fromkeys(item for item in cleaned if item))


class PronunciationTrainer:
    def __init__(
        self,
        bus: EventBus,
        vocabulary: VocabularyRepository,
        bindings: BindingRepository,
        microphone: MicrophoneStream,
        recorder: UtteranceRecorder,
        sample_transcriber: SampleTranscriber,
        extractor: FeatureExtractor,
        builder: AcousticModelBuilder,
        scorer: PronunciationScorer,
        settings: TrainingSection,
        voice_dir: Path,
    ) -> None:
        self._bus = bus
        self._vocabulary = vocabulary
        self._bindings = bindings
        self._microphone = microphone
        self._recorder = recorder
        self._sample_transcriber = sample_transcriber
        self._extractor = extractor
        self._builder = builder
        self._scorer = scorer
        self._settings = settings
        self._voice_dir = voice_dir
        self._jobs: queue.Queue[object] = queue.Queue()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        handlers: dict[type[Event], Callable[[Any], None]] = {
            VocabularyWordAddRequested: lambda event: self._add_word(event.text, event.action),
            TrainingStartRequested: lambda event: self._start_session(event.word_id),
            TrainingSampleRequested: lambda event: self._record_sample(event.word_id),
            TrainingSampleDeleteRequested: lambda event: self._delete_sample(event.word_id, event.sample_id),
            TrainingFinishRequested: lambda event: self._finish(event.word_id),
            TrainingTestRequested: lambda event: self._test(event.word_id),
            TrainingSaveRequested: lambda event: self._save(event.word_id),
            TrainingSessionClosed: lambda event: self._close_session(),
        }
        for event_type, handler in handlers.items():
            self._bus.subscribe(event_type, partial(self._enqueue, handler))
        self._bus.subscribe(ShutdownRequested, lambda _: self._jobs.put(_STOP))
        self._thread = threading.Thread(target=self._run, name="pronunciation-trainer", daemon=True)
        self._thread.start()

    def _enqueue(self, handler: Callable[[Any], None], event: Event) -> None:
        word_id = getattr(event, "word_id", None)
        self._jobs.put(_TrainingJob(word_id, partial(handler, event)))

    def _run(self) -> None:
        while True:
            item = self._jobs.get()
            if item is _STOP:
                return
            if isinstance(item, _TrainingJob):
                self._execute(item.word_id, item.run)

    def _execute(self, word_id: int | None, job: Job) -> None:
        try:
            job()
        except EmptyRecordingError:
            self._bus.publish(TrainingFailed(word_id, "Не почув слова. Скажіть його чіткіше й трохи голосніше."))
        except NotEnoughSamplesError:
            self._bus.publish(
                TrainingFailed(word_id, f"Потрібно щонайменше {self._settings.min_samples} зразки.")
            )
        except (TrainingError, RecognitionError, AudioDeviceError) as error:
            self._bus.publish(TrainingFailed(word_id, str(error)))
        except JarvisError as error:
            logger.exception("Помилка навчання")
            self._bus.publish(TrainingFailed(word_id, f"Помилка: {error}"))

    def _add_word(self, text: str, action: Action | None) -> None:
        normalized = TextNormalizer.basic(text)
        if not normalized:
            raise TrainingError("Введіть слово")
        word = self._vocabulary.add_word(text.strip(), normalized, action)
        self._bus.publish(VocabularyChanged())
        self._open_session(word)

    def _start_session(self, word_id: int) -> None:
        self._open_session(self._require_word(word_id))

    def _open_session(self, word: VocabularyWord) -> None:
        if word.id is None:
            raise TrainingError("Слово без ідентифікатора")
        self._bus.publish(ListenerPauseRequested(True, PAUSE_REASON))
        samples = tuple(self._vocabulary.list_samples(word.id))
        self._bus.publish(TrainingSessionStarted(word, samples))

    def _close_session(self) -> None:
        self._bus.publish(ListenerPauseRequested(False, PAUSE_REASON))

    def _record_sample(self, word_id: int) -> None:
        self._require_word(word_id)
        recorded = self._record(word_id)
        path = self._voice_dir / str(word_id) / f"sample_{uuid.uuid4().hex[:10]}.wav"
        WavFile.write(path, recorded.pcm, self._microphone.sample_rate)
        features = serialize_features(self._extractor.extract(recorded.pcm, self._microphone.sample_rate))
        duration = len(recorded.pcm) / (2 * self._microphone.sample_rate)
        self._vocabulary.add_sample(word_id, path, duration, recorded.transcripts, features)
        self._publish_samples(word_id)

    def _record(self, word_id: int) -> RecordedSample:
        subscription = self._microphone.subscribe()
        self._bus.publish(TrainingRecordingStarted(word_id))
        try:
            pcm = self._recorder.record(
                subscription,
                RecordingLimits(
                    max_seconds=self._settings.max_sample_seconds,
                    end_silence_seconds=self._settings.end_silence_seconds,
                    start_timeout_seconds=START_TIMEOUT_SECONDS,
                ),
                on_level=lambda level: self._bus.publish(MicLevelChanged(level)),
            )
        finally:
            subscription.close()
        return RecordedSample(pcm, self._sample_transcriber.transcripts(pcm))

    def _delete_sample(self, word_id: int, sample_id: int) -> None:
        sample = self._vocabulary.delete_sample(sample_id)
        if sample is not None:
            sample.file_path.unlink(missing_ok=True)
        self._publish_samples(word_id)

    def _publish_samples(self, word_id: int) -> None:
        self._bus.publish(TrainingSamplesChanged(word_id, tuple(self._vocabulary.list_samples(word_id))))

    def _finish(self, word_id: int) -> None:
        samples = self._vocabulary.list_samples(word_id)
        if len(samples) < self._settings.min_samples:
            raise NotEnoughSamplesError(str(len(samples)))
        model = self._builder.build([self._features(sample) for sample in samples])
        for transcript in dict.fromkeys(text for sample in samples for text in sample.transcripts):
            self._vocabulary.upsert_alias(word_id, transcript, transcript, AliasSource.TRAINING)
        word = self._require_word(word_id)
        self._vocabulary.mark_trained(word_id, model.threshold, word.is_trained)
        self._bus.publish(VocabularyChanged())
        refreshed = self._require_word(word_id)
        self._bus.publish(TrainingModelBuilt(word_id, refreshed.aliases, model.threshold))
        logger.info("Модель слова «%s»: поріг DTW %.3f, аліасів %d", word.text, model.threshold, len(refreshed.aliases))

    def _features(self, sample: VoiceSample) -> FloatArray:
        if sample.features:
            return deserialize_features(sample.features)
        pcm, rate = WavFile.read(sample.file_path)
        features = self._extractor.extract(pcm, rate)
        if sample.id is not None:
            self._vocabulary.update_sample_features(sample.id, serialize_features(features))
        return features

    def _test(self, word_id: int) -> None:
        word = self._require_word(word_id)
        recorded = self._record(word_id)
        model = self._acoustic_model(word)
        alias_score = max(
            (self._scorer.alias_score(text, word)[0] for text in recorded.transcripts), default=0.0
        )
        acoustic = self._scorer.acoustic_score(model, recorded.pcm, self._microphone.sample_rate)
        combined = self._scorer.combine(alias_score, acoustic)
        self._bus.publish(
            TrainingTestResult(
                word_id=word_id,
                transcript=recorded.transcripts[0] if recorded.transcripts else "(нічого)",
                alias_score=alias_score,
                acoustic_score=acoustic,
                combined_score=combined,
                matched=self._scorer.is_match(alias_score, acoustic, combined),
            )
        )

    def _acoustic_model(self, word: VocabularyWord) -> AcousticModel | None:
        if word.id is None or not word.acoustic_threshold:
            return None
        templates = [self._features(sample) for sample in self._vocabulary.list_samples(word.id)]
        if not templates:
            return None
        return AcousticModel(tuple(templates), float(word.acoustic_threshold))

    def _save(self, word_id: int) -> None:
        word = self._require_word(word_id)
        if not word.acoustic_threshold:
            raise TrainingError("Спершу натисніть «Завершити», щоб побудувати модель")
        self._vocabulary.mark_trained(word_id, word.acoustic_threshold, True)
        self._bind_action(word)
        self._bus.publish(VocabularyChanged())
        self._bus.publish(TrainingSaved(word_id))

    def _bind_action(self, word: VocabularyWord) -> None:
        if word.action is None:
            return
        self._bindings.save(
            Binding(id=None, phrase=word.text, normalized=word.normalized, action=word.action, source=BindingSource.USER)
        )
        self._bus.publish(BindingsChanged())

    def _require_word(self, word_id: int) -> VocabularyWord:
        word = self._vocabulary.get_word(word_id)
        if word is None:
            raise TrainingError("Слово не знайдено")
        return word
