from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from jarvis.core.config import SpeechSection
from jarvis.core.errors import JarvisError, RecognitionError
from jarvis.core.event_bus import EventBus
from jarvis.core.events import (
    AssistantStateChanged,
    CommandReceived,
    ErrorOccurred,
    ListenerPauseRequested,
    ListenRequested,
    MicLevelChanged,
    SpeakRequested,
    SpeechFinished,
    SpeechStarted,
    WakeWordDetected,
)
from jarvis.core.speech_types import AssistantState, CommandSource, Utterance
from jarvis.speech.audio_io import (
    AudioSubscription,
    MicrophoneStream,
    RecordingLimits,
    UtteranceSegmenter,
    chunk_level,
)
from jarvis.speech.grammar import GrammarProvider
from jarvis.speech.recognizer_vosk import SpeechTranscriber
from jarvis.speech.wake_word import WakeDetection, WakeWordDetector

logger = logging.getLogger(__name__)

LEVEL_PUBLISH_INTERVAL = 0.08
COMMAND_END_SILENCE = 0.8
NOT_HEARD_REPLY = "Не розчув, сер."


class VoiceListener:
    def __init__(
        self,
        bus: EventBus,
        microphone: MicrophoneStream,
        transcriber: SpeechTranscriber,
        detector_factory: Callable[[], WakeWordDetector],
        grammar: GrammarProvider,
        settings: SpeechSection,
    ) -> None:
        self._bus = bus
        self._microphone = microphone
        self._transcriber = transcriber
        self._detector_factory = detector_factory
        self._grammar = grammar
        self._settings = settings
        self._running = threading.Event()
        self._listen_requested = threading.Event()
        self._speaking = threading.Event()
        self._pause_reasons: set[str] = set()
        self._pause_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._subscription: AudioSubscription | None = None
        self._detector: WakeWordDetector | None = None
        self._capture: UtteranceSegmenter | None = None
        self._last_level_at = 0.0

    def start(self) -> None:
        self._bus.subscribe(ListenRequested, self._on_listen_requested)
        self._bus.subscribe(SpeechStarted, self._on_speech_started)
        self._bus.subscribe(SpeechFinished, self._on_speech_finished)
        self._bus.subscribe(ListenerPauseRequested, self._on_pause_requested)
        self._subscription = self._microphone.subscribe()
        self._running.set()
        self._thread = threading.Thread(target=self._run, name="voice-listener", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running.clear()
        if self._subscription is not None:
            self._subscription.close()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _on_listen_requested(self, event: ListenRequested) -> None:
        self._listen_requested.set()

    def _on_speech_started(self, event: SpeechStarted) -> None:
        self._speaking.set()
        self._restart_capture_if_idle()

    def _on_speech_finished(self, event: SpeechFinished) -> None:
        self._speaking.clear()
        self._restart_capture_if_idle()

    def _on_pause_requested(self, event: ListenerPauseRequested) -> None:
        with self._pause_lock:
            if event.paused:
                self._pause_reasons.add(event.reason)
            else:
                self._pause_reasons.discard(event.reason)

    def _is_paused(self) -> bool:
        with self._pause_lock:
            return bool(self._pause_reasons)

    def _restart_capture_if_idle(self) -> None:
        capture = self._capture
        if capture is not None and not capture.speech_started:
            self._capture = self._new_segmenter()

    def _run(self) -> None:
        subscription = self._subscription
        if subscription is None:
            return
        self._detector = self._create_detector()
        while self._running.is_set():
            chunk = subscription.read(timeout=0.2)
            self._start_requested_capture()
            if chunk is None:
                self._check_capture_timeout()
                continue
            self._process_chunk(chunk)

    def _create_detector(self) -> WakeWordDetector | None:
        if not self._settings.wake.enabled:
            return None
        try:
            return self._detector_factory()
        except JarvisError as error:
            logger.error("Wake word недоступний: %s", error)
            self._bus.publish(ErrorOccurred(f"Розпізнавання мови недоступне: {error}"))
            return None

    def _start_requested_capture(self) -> None:
        if not self._listen_requested.is_set():
            return
        self._listen_requested.clear()
        self._begin_capture()

    def _process_chunk(self, chunk: bytes) -> None:
        level = chunk_level(chunk)
        self._publish_level(level)
        if self._is_paused():
            self._reset_detection()
            return
        if self._speaking.is_set():
            return
        if self._capture is not None:
            self._feed_capture(chunk, level)
            return
        if self._detector is not None:
            self._handle_wake(self._detector.feed(chunk))

    def _reset_detection(self) -> None:
        self._capture = None
        if self._detector is not None:
            self._detector.reset()

    def _publish_level(self, level: float) -> None:
        now = time.monotonic()
        if now - self._last_level_at < LEVEL_PUBLISH_INTERVAL:
            return
        self._last_level_at = now
        self._bus.publish(MicLevelChanged(level))

    def _handle_wake(self, detection: WakeDetection | None) -> None:
        if detection is None:
            return
        if not detection.final:
            self._announce_wake()
            return
        if not detection.matched:
            self._bus.publish(AssistantStateChanged(AssistantState.IDLE))
            return
        self._announce_wake()
        if detection.tail_word_count > 0 and detection.tail_seconds >= self._settings.wake.min_command_tail_seconds:
            self._submit(detection.tail_audio)
            return
        self._begin_capture()

    def _announce_wake(self) -> None:
        self._bus.publish(WakeWordDetected("джарвіс"))
        self._bus.publish(AssistantStateChanged(AssistantState.LISTENING))

    def _begin_capture(self) -> None:
        if self._detector is not None:
            self._detector.reset()
        self._capture = self._new_segmenter()
        self._bus.publish(AssistantStateChanged(AssistantState.LISTENING))

    def _new_segmenter(self) -> UtteranceSegmenter:
        limits = RecordingLimits(
            max_seconds=self._settings.max_command_seconds,
            end_silence_seconds=COMMAND_END_SILENCE,
            start_timeout_seconds=self._settings.command_timeout_seconds,
        )
        return UtteranceSegmenter(self._microphone.sample_rate, limits)

    def _feed_capture(self, chunk: bytes, level: float) -> None:
        capture = self._capture
        if capture is None:
            return
        if capture.feed(chunk, level):
            self._capture = None
            self._submit(capture.audio)
            return
        self._check_capture_timeout()

    def _check_capture_timeout(self) -> None:
        capture = self._capture
        if capture is None or self._speaking.is_set() or not capture.timed_out():
            return
        self._capture = None
        logger.info("Команду не почуто — повертаюсь до очікування wake word")
        self._bus.publish(AssistantStateChanged(AssistantState.IDLE))

    def _submit(self, pcm: bytes) -> None:
        self._bus.publish(AssistantStateChanged(AssistantState.THINKING))
        try:
            transcript = self._transcriber.transcribe_command(pcm, self._grammar.phrases())
        except RecognitionError as error:
            logger.error("Помилка розпізнавання: %s", error)
            self._bus.publish(ErrorOccurred(str(error)))
            self._bus.publish(AssistantStateChanged(AssistantState.IDLE))
            return
        if transcript.is_empty:
            self._bus.publish(SpeakRequested(NOT_HEARD_REPLY))
            self._bus.publish(AssistantStateChanged(AssistantState.IDLE))
            return
        logger.info("Розпізнано: «%s» (%.2f)", transcript.text, transcript.confidence)
        utterance = Utterance(transcript=transcript, audio=pcm, sample_rate=self._microphone.sample_rate)
        self._bus.publish(CommandReceived(transcript.text, CommandSource.VOICE, utterance))
