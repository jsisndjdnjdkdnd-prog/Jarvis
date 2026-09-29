from __future__ import annotations

import logging
import math
import queue
import threading
import time
import wave
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from jarvis.core.errors import AudioDeviceError, EmptyRecordingError

logger = logging.getLogger(__name__)

SAMPLE_WIDTH_BYTES = 2
MAX_INT16 = 32768.0
LevelCallback = Callable[[float], None]


def chunk_level(chunk: bytes) -> float:
    if not chunk:
        return 0.0
    samples = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / MAX_INT16
    rms = float(np.sqrt(np.mean(samples**2))) if samples.size else 0.0
    return min(1.0, rms * 6.0)


def pcm_duration(pcm: bytes | bytearray, sample_rate: int) -> float:
    return len(pcm) / (SAMPLE_WIDTH_BYTES * sample_rate)


class AudioSubscription:
    def __init__(self, owner: MicrophoneStream, max_chunks: int) -> None:
        self._owner = owner
        self._queue: queue.Queue[bytes] = queue.Queue(maxsize=max_chunks)

    def push(self, chunk: bytes) -> None:
        try:
            self._queue.put_nowait(chunk)
        except queue.Full:
            self._drop_oldest()
            self._queue.put_nowait(chunk)

    def _drop_oldest(self) -> None:
        try:
            self._queue.get_nowait()
        except queue.Empty:
            return

    def read(self, timeout: float) -> bytes | None:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def drain(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return

    def close(self) -> None:
        self._owner.unsubscribe(self)


class MicrophoneStream:
    def __init__(self, sample_rate: int, block_size: int, device: int | str | None) -> None:
        self._sample_rate = sample_rate
        self._block_size = block_size
        self._device = device
        self._subscribers: list[AudioSubscription] = []
        self._lock = threading.Lock()
        self._stream: Any = None

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    def start(self) -> None:
        import sounddevice as sd

        if self._stream is not None:
            return
        try:
            self._stream = sd.RawInputStream(
                samplerate=self._sample_rate,
                blocksize=self._block_size,
                device=self._device,
                dtype="int16",
                channels=1,
                callback=self._on_audio,
            )
            self._stream.start()
        except (sd.PortAudioError, ValueError) as error:
            self._stream = None
            raise AudioDeviceError(f"Не вдалося відкрити мікрофон: {error}") from error
        logger.info("Мікрофон запущено (%d Гц, блок %d)", self._sample_rate, self._block_size)

    def stop(self) -> None:
        if self._stream is None:
            return
        self._stream.stop()
        self._stream.close()
        self._stream = None

    def subscribe(self, max_chunks: int = 400) -> AudioSubscription:
        subscription = AudioSubscription(self, max_chunks)
        with self._lock:
            self._subscribers.append(subscription)
        return subscription

    def unsubscribe(self, subscription: AudioSubscription) -> None:
        with self._lock:
            if subscription in self._subscribers:
                self._subscribers.remove(subscription)

    def _on_audio(self, data: Any, frames: int, time_info: Any, status: Any) -> None:
        if status:
            logger.debug("Статус аудіопотоку: %s", status)
        chunk = bytes(data)
        with self._lock:
            subscribers = list(self._subscribers)
        for subscriber in subscribers:
            subscriber.push(chunk)


class EnergyVad:
    def __init__(self, ratio: float = 2.8, min_level: float = 0.035, adaptation: float = 0.05) -> None:
        self._ratio = ratio
        self._min_level = min_level
        self._adaptation = adaptation
        self._noise = min_level / ratio

    def is_speech(self, level: float) -> bool:
        speech = level > max(self._min_level, self._noise * self._ratio)
        if not speech:
            self._noise = (1 - self._adaptation) * self._noise + self._adaptation * level
        return speech


@dataclass(frozen=True)
class RecordingLimits:
    max_seconds: float
    end_silence_seconds: float
    start_timeout_seconds: float


class UtteranceSegmenter:
    def __init__(
        self,
        sample_rate: int,
        limits: RecordingLimits,
        vad: EnergyVad | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._sample_rate = sample_rate
        self._limits = limits
        self._vad = vad or EnergyVad()
        self._clock = clock
        self._started_at = clock()
        self._pre_roll: list[bytes] = []
        self._audio = bytearray()
        self._silence = 0.0
        self._speech_started = False

    @property
    def speech_started(self) -> bool:
        return self._speech_started

    @property
    def audio(self) -> bytes:
        return bytes(self._audio)

    def timed_out(self) -> bool:
        if self._speech_started:
            return False
        return self._clock() - self._started_at > self._limits.start_timeout_seconds

    def feed(self, chunk: bytes, level: float) -> bool:
        if self._vad.is_speech(level):
            self._mark_speech()
        elif self._speech_started:
            self._silence += pcm_duration(chunk, self._sample_rate)
        if not self._speech_started:
            self._pre_roll = (self._pre_roll + [chunk])[-3:]
            return False
        self._audio.extend(chunk)
        if self._silence >= self._limits.end_silence_seconds:
            return True
        return pcm_duration(self._audio, self._sample_rate) >= self._limits.max_seconds

    def _mark_speech(self) -> None:
        if not self._speech_started:
            self._audio.extend(b"".join(self._pre_roll))
            self._pre_roll = []
        self._speech_started = True
        self._silence = 0.0


class UtteranceRecorder:
    def __init__(self, sample_rate: int) -> None:
        self._sample_rate = sample_rate

    def record(
        self,
        subscription: AudioSubscription,
        limits: RecordingLimits,
        on_level: LevelCallback | None = None,
        should_continue: Callable[[], bool] = lambda: True,
    ) -> bytes:
        segmenter = UtteranceSegmenter(self._sample_rate, limits)
        while should_continue() and not segmenter.timed_out():
            chunk = subscription.read(timeout=0.3)
            if chunk is None:
                continue
            level = chunk_level(chunk)
            if on_level is not None:
                on_level(level)
            if segmenter.feed(chunk, level):
                break
        if not segmenter.speech_started:
            raise EmptyRecordingError("Не почув мови")
        return segmenter.audio


class WavFile:
    @staticmethod
    def write(path: Path, pcm: bytes, sample_rate: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(SAMPLE_WIDTH_BYTES)
            handle.setframerate(sample_rate)
            handle.writeframes(pcm)

    @staticmethod
    def read(path: Path) -> tuple[bytes, int]:
        with wave.open(str(path), "rb") as handle:
            return handle.readframes(handle.getnframes()), handle.getframerate()


class AudioPlayer:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._interrupted = threading.Event()

    def play_samples(self, samples: np.ndarray, sample_rate: int) -> None:
        import sounddevice as sd

        with self._lock:
            self._interrupted.clear()
            try:
                sd.play(samples, samplerate=sample_rate)
                sd.wait()
            except sd.PortAudioError as error:
                raise AudioDeviceError(f"Помилка відтворення: {error}") from error

    def interrupt(self) -> None:
        import sounddevice as sd

        self._interrupted.set()
        try:
            sd.stop()
        except sd.PortAudioError as error:
            logger.debug("Не вдалося зупинити відтворення: %s", error)

    def play_file(self, path: Path) -> None:
        import miniaudio

        try:
            decoded = miniaudio.decode_file(
                str(path), output_format=miniaudio.SampleFormat.SIGNED16, nchannels=1
            )
        except miniaudio.DecodeError as error:
            raise AudioDeviceError(f"Не вдалося декодувати {path.name}: {error}") from error
        samples = np.frombuffer(decoded.samples, dtype=np.int16)
        self.play_samples(samples, decoded.sample_rate)

    def beep(self, frequency: float = 880.0, seconds: float = 0.25, repeats: int = 3) -> None:
        sample_rate = 22050
        timeline = np.arange(int(sample_rate * seconds)) / sample_rate
        envelope = np.minimum(1.0, np.minimum(timeline, seconds - timeline) * 40)
        tone = 0.35 * np.sin(2 * math.pi * frequency * timeline) * envelope
        pause = np.zeros(int(sample_rate * 0.12))
        signal = np.concatenate([np.concatenate([tone, pause]) for _ in range(repeats)])
        self.play_samples(signal.astype(np.float32), sample_rate)
