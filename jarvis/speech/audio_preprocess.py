from __future__ import annotations

import logging
from math import gcd

import numpy as np
from scipy import signal

logger = logging.getLogger(__name__)

INT16_MIN = -32768
INT16_MAX = 32767
INT16_SCALE = 32768.0
SAMPLE_WIDTH = 2
SILENCE_PEAK = 1e-4
HIGHPASS_ORDER = 2


def pcm_to_float32(pcm: bytes) -> np.ndarray:
    usable = len(pcm) - len(pcm) % SAMPLE_WIDTH
    samples = np.frombuffer(pcm[:usable], dtype="<i2")
    return samples.astype(np.float32) / np.float32(INT16_SCALE)


def float_to_pcm(audio: np.ndarray) -> bytes:
    scaled = np.round(np.asarray(audio, dtype=np.float64) * INT16_SCALE)
    return np.clip(scaled, INT16_MIN, INT16_MAX).astype("<i2").tobytes()


def resample(audio: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    if source_rate == target_rate or audio.size == 0:
        return audio
    divisor = gcd(source_rate, target_rate)
    converted = signal.resample_poly(audio, target_rate // divisor, source_rate // divisor)
    return np.asarray(converted, dtype=np.float32)


class AudioPreprocessor:
    def __init__(
        self,
        sample_rate: int,
        target_peak: float = 0.7,
        max_gain: float = 8.0,
        highpass_hz: float = 80.0,
    ) -> None:
        self._sample_rate = sample_rate
        self._target_peak = min(max(target_peak, 0.0), 1.0)
        self._max_gain = max_gain
        self._highpass = self._design_highpass(sample_rate, highpass_hz)

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    def process(self, pcm: bytes) -> bytes:
        audio = pcm_to_float32(pcm).astype(np.float64)
        if audio.size == 0:
            return b""
        centered = audio - audio.mean()
        return float_to_pcm(self._normalize(self._filter(centered)))

    def to_float32(self, pcm: bytes) -> np.ndarray:
        return pcm_to_float32(pcm)

    def _filter(self, audio: np.ndarray) -> np.ndarray:
        if self._highpass is None:
            return audio
        initial = signal.sosfilt_zi(self._highpass) * audio[0]
        filtered, _ = signal.sosfilt(self._highpass, audio, zi=initial)
        return np.asarray(filtered, dtype=np.float64)

    def _normalize(self, audio: np.ndarray) -> np.ndarray:
        peak = float(np.max(np.abs(audio)))
        if peak < SILENCE_PEAK:
            return audio
        gain = min(self._target_peak / peak, self._max_gain)
        return audio * gain

    @staticmethod
    def _design_highpass(sample_rate: int, cutoff_hz: float) -> np.ndarray | None:
        if cutoff_hz <= 0 or cutoff_hz >= sample_rate / 2:
            logger.debug("High-pass фільтр вимкнено: %.1f Гц при %d Гц", cutoff_hz, sample_rate)
            return None
        return signal.butter(HIGHPASS_ORDER, cutoff_hz, btype="highpass", fs=sample_rate, output="sos")
