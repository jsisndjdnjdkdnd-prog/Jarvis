from __future__ import annotations

import numpy as np
import pytest

from jarvis.core.errors import EmptyRecordingError, NotEnoughSamplesError
from jarvis.training.voice_templates import (
    AcousticModelBuilder,
    DtwComparer,
    MfccExtractor,
    ThresholdEstimator,
    deserialize_features,
    serialize_features,
    trim_silence,
)

SAMPLE_RATE = 16000


def naive_dtw(first: np.ndarray, second: np.ndarray) -> float:
    rows, cols = len(first), len(second)
    cost = np.full((rows + 1, cols + 1), np.inf)
    cost[0, 0] = 0.0
    for i in range(1, rows + 1):
        for j in range(1, cols + 1):
            local = np.linalg.norm(first[i - 1] - second[j - 1])
            cost[i, j] = local + min(cost[i - 1, j], cost[i, j - 1], cost[i - 1, j - 1])
    return float(cost[rows, cols]) / (rows + cols)


def tone(frequencies: tuple[float, ...], seconds: float = 0.6, seed: int = 0) -> bytes:
    rng = np.random.default_rng(seed)
    timeline = np.arange(int(SAMPLE_RATE * seconds)) / SAMPLE_RATE
    segment = len(timeline) // len(frequencies)
    signal = np.concatenate(
        [np.sin(2 * np.pi * frequency * timeline[:segment]) for frequency in frequencies]
    )
    noisy = 0.5 * signal + 0.01 * rng.standard_normal(len(signal))
    silence = np.zeros(SAMPLE_RATE // 5)
    return (np.concatenate([silence, noisy, silence]) * 32767).astype(np.int16).tobytes()


def test_vectorized_dtw_equals_reference() -> None:
    rng = np.random.default_rng(42)
    first = rng.standard_normal((23, 5))
    second = rng.standard_normal((31, 5))
    assert DtwComparer().distance(first, second) == pytest.approx(naive_dtw(first, second))


def test_dtw_identity_is_zero() -> None:
    features = np.random.default_rng(1).standard_normal((10, 4))
    assert DtwComparer().distance(features, features) == pytest.approx(0.0)


def test_trim_silence_removes_padding() -> None:
    pcm = np.frombuffer(tone((440.0,)), dtype=np.int16).astype(np.float64) / 32768
    trimmed = trim_silence(pcm, SAMPLE_RATE)
    assert len(trimmed) < len(pcm)
    assert len(trimmed) > SAMPLE_RATE * 0.5


def test_silence_raises() -> None:
    with pytest.raises(EmptyRecordingError):
        MfccExtractor().extract(np.zeros(SAMPLE_RATE, dtype=np.int16).tobytes(), SAMPLE_RATE)


def test_same_word_is_closer_than_other_word() -> None:
    extractor = MfccExtractor()
    comparer = DtwComparer()
    word = [extractor.extract(tone((300.0, 900.0, 500.0), seed=seed), SAMPLE_RATE) for seed in range(4)]
    other = extractor.extract(tone((1500.0, 200.0, 2500.0), seed=9), SAMPLE_RATE)
    model = AcousticModelBuilder(comparer, ThresholdEstimator()).build(word[:3])
    assert model.best_distance(word[3], comparer) < model.best_distance(other, comparer)
    assert model.similarity(word[3], comparer) > model.similarity(other, comparer)


def test_threshold_requires_two_templates() -> None:
    with pytest.raises(NotEnoughSamplesError):
        ThresholdEstimator().estimate([np.zeros((3, 2))], DtwComparer())


def test_features_serialization_roundtrip() -> None:
    features = np.random.default_rng(3).standard_normal((12, 26))
    restored = deserialize_features(serialize_features(features))
    assert restored.shape == features.shape
    assert np.allclose(restored, features, atol=1e-5)
