from __future__ import annotations

import io
import itertools
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

import numpy as np
from numpy.typing import NDArray

from jarvis.core.errors import EmptyRecordingError, NotEnoughSamplesError

FloatArray = NDArray[np.float64]

FRAME_SECONDS = 0.02
MIN_SPEECH_SECONDS = 0.15
SILENCE_RATIO = 0.08
NOISE_FLOOR = 0.004
SEGMENT_PADDING_FRAMES = 2


def pcm16_to_float(pcm: bytes | NDArray[np.int16]) -> FloatArray:
    samples = np.frombuffer(pcm, dtype=np.int16) if isinstance(pcm, bytes | bytearray) else pcm
    return samples.astype(np.float64) / 32768.0


def trim_silence(signal: FloatArray, sample_rate: int) -> FloatArray:
    frame = max(1, int(sample_rate * FRAME_SECONDS))
    usable = len(signal) - len(signal) % frame
    if usable <= 0:
        return signal[:0]
    energies = np.sqrt(np.mean(signal[:usable].reshape(-1, frame) ** 2, axis=1))
    threshold = max(float(energies.max()) * SILENCE_RATIO, NOISE_FLOOR)
    voiced = np.flatnonzero(energies > threshold)
    if voiced.size == 0:
        return signal[:0]
    start = max(0, int(voiced[0]) - SEGMENT_PADDING_FRAMES) * frame
    end = min(len(signal), (int(voiced[-1]) + 1 + SEGMENT_PADDING_FRAMES) * frame)
    return signal[start:end]


class FeatureExtractor(Protocol):
    def extract(self, pcm: bytes | NDArray[np.int16], sample_rate: int) -> FloatArray: ...


class MfccExtractor:
    def __init__(self, num_features: int = 13, include_deltas: bool = True) -> None:
        self._num_features = num_features
        self._include_deltas = include_deltas

    def extract(self, pcm: bytes | NDArray[np.int16], sample_rate: int) -> FloatArray:
        from python_speech_features import delta, mfcc

        signal = trim_silence(pcm16_to_float(pcm), sample_rate)
        if len(signal) < int(sample_rate * MIN_SPEECH_SECONDS):
            raise EmptyRecordingError("Не чути мови у записі")
        features = mfcc(
            signal,
            samplerate=sample_rate,
            winlen=0.025,
            winstep=0.01,
            numcep=self._num_features,
            nfilt=26,
            nfft=512,
            appendEnergy=True,
        )
        if self._include_deltas:
            features = np.hstack([features, delta(features, 2)])
        return self._normalize(np.asarray(features, dtype=np.float64))

    @staticmethod
    def _normalize(features: FloatArray) -> FloatArray:
        mean = features.mean(axis=0, keepdims=True)
        std = features.std(axis=0, keepdims=True)
        return (features - mean) / np.where(std < 1e-8, 1.0, std)


class DtwComparer:
    def distance(self, first: FloatArray, second: FloatArray) -> float:
        if len(first) == 0 or len(second) == 0:
            return float("inf")
        local = self._local_costs(first, second)
        accumulated = np.cumsum(local[0])
        for row in local[1:]:
            accumulated = self._next_row(accumulated, row)
        return float(accumulated[-1]) / (len(first) + len(second))

    @staticmethod
    def _local_costs(first: FloatArray, second: FloatArray) -> FloatArray:
        differences = first[:, np.newaxis, :] - second[np.newaxis, :, :]
        return np.sqrt(np.einsum("ijk,ijk->ij", differences, differences))

    @staticmethod
    def _next_row(previous: FloatArray, row: FloatArray) -> FloatArray:
        diagonal = np.concatenate(([np.inf], previous[:-1]))
        best_above = np.minimum(previous, diagonal)
        prefix = np.cumsum(row)
        shifted = np.concatenate(([0.0], prefix[:-1]))
        return prefix + np.minimum.accumulate(best_above - shifted)


@dataclass(frozen=True)
class AcousticModel:
    templates: tuple[FloatArray, ...]
    threshold: float

    def best_distance(self, features: FloatArray, comparer: DtwComparer) -> float:
        return min(comparer.distance(features, template) for template in self.templates)

    def similarity(self, features: FloatArray, comparer: DtwComparer) -> float:
        distance = self.best_distance(features, comparer)
        if self.threshold <= 0:
            return 0.0
        return float(np.clip(1.5 - distance / self.threshold, 0.0, 1.0))


class ThresholdEstimator:
    def __init__(self, std_factor: float = 2.0, min_margin: float = 1.15) -> None:
        self._std_factor = std_factor
        self._min_margin = min_margin

    def estimate(self, templates: Sequence[FloatArray], comparer: DtwComparer) -> float:
        if len(templates) < 2:
            raise NotEnoughSamplesError("Для порогу потрібно щонайменше два зразки")
        distances = np.array(
            [comparer.distance(first, second) for first, second in itertools.combinations(templates, 2)]
        )
        mean = float(distances.mean())
        spread = float(distances.std())
        return max(mean + self._std_factor * spread, mean * self._min_margin)


class AcousticModelBuilder:
    def __init__(self, comparer: DtwComparer, estimator: ThresholdEstimator) -> None:
        self._comparer = comparer
        self._estimator = estimator

    def build(self, templates: Sequence[FloatArray]) -> AcousticModel:
        threshold = self._estimator.estimate(templates, self._comparer)
        return AcousticModel(templates=tuple(templates), threshold=threshold)


def serialize_features(features: FloatArray) -> bytes:
    buffer = io.BytesIO()
    np.save(buffer, features.astype(np.float32), allow_pickle=False)
    return buffer.getvalue()


def deserialize_features(blob: bytes) -> FloatArray:
    return np.load(io.BytesIO(blob), allow_pickle=False).astype(np.float64)
