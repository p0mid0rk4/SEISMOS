"""Цифровая обработка сейсмических сигналов.

Реализованы минимально необходимые примитивы: полосовой БИХ-фильтр
(биквадратный каскад), огибающая, СКЗ, признаки спектра (БПФ) и число
переходов через ноль. Реализация опирается только на NumPy.
"""

from __future__ import annotations

import math

import numpy as np

__all__ = [
    "BandPass",
    "envelope",
    "rms",
    "spectral_features",
    "zero_crossing_rate",
]


class BandPass:
    """Каскад биквадратных (biquad) полосовых фильтров.

    Полоса по умолчанию 5–120 Гц соответствует частотному диапазону
    геофона GS-20DX (собственная частота 4.5 Гц) и интересующей нас
    области сейсмических сигналов от шагов и техники.
    """

    def __init__(self, sample_rate: int, low_hz: float, high_hz: float, order: int = 2) -> None:
        self.sample_rate = sample_rate
        self.low_hz = low_hz
        self.high_hz = high_hz
        self.order = max(1, order)
        self._hp = [self._make_highpass(low_hz) for _ in range(self.order)]
        self._lp = [self._make_lowpass(high_hz) for _ in range(self.order)]
        self._state = [np.zeros(2) for _ in range(2 * self.order)]

    # -- коэффициенты ---------------------------------------------------
    def _make_lowpass(self, fc: float) -> tuple[float, float, float, float, float]:
        w0 = 2.0 * math.pi * fc / self.sample_rate
        alpha = math.sin(w0) / (2.0 * math.sqrt(0.5))  # Q = 0.707
        cos_w0 = math.cos(w0)
        b0 = (1.0 - cos_w0) / 2.0
        b1 = 1.0 - cos_w0
        b2 = (1.0 - cos_w0) / 2.0
        a0 = 1.0 + alpha
        a1 = -2.0 * cos_w0
        a2 = 1.0 - alpha
        return (b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0)

    def _make_highpass(self, fc: float) -> tuple[float, float, float, float, float]:
        w0 = 2.0 * math.pi * fc / self.sample_rate
        alpha = math.sin(w0) / (2.0 * math.sqrt(0.5))
        cos_w0 = math.cos(w0)
        b0 = (1.0 + cos_w0) / 2.0
        b1 = -(1.0 + cos_w0)
        b2 = (1.0 + cos_w0) / 2.0
        a0 = 1.0 + alpha
        a1 = -2.0 * cos_w0
        a2 = 1.0 - alpha
        return (b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0)

    @staticmethod
    def _apply_section(
        x: np.ndarray, coef: tuple[float, float, float, float, float],
        state: np.ndarray,
    ) -> np.ndarray:
        b0, b1, b2, a1, a2 = coef
        z1, z2 = state[0], state[1]
        out = np.empty_like(x)
        for i in range(x.size):
            v = x[i] - a1 * z1 - a2 * z2
            out[i] = b0 * v + b1 * z1 + b2 * z2
            z2 = z1
            z1 = v
        state[0], state[1] = z1, z2
        return out

    def process(self, x: np.ndarray) -> np.ndarray:
        y = np.asarray(x, dtype=np.float64)
        for i, sec in enumerate(self._hp):
            y = self._apply_section(y, sec, self._state[i])
        for j, sec in enumerate(self._lp):
            y = self._apply_section(y, sec, self._state[self.order + j])
        return y

    def reset(self) -> None:
        for st in self._state:
            st[:] = 0.0


def envelope(x: np.ndarray, sample_rate: int, smooth_ms: float = 20.0) -> np.ndarray:
    """Огибающая сигнала через модуль с экспоненциальным сглаживанием."""
    x = np.asarray(x, dtype=np.float64)
    rect = np.abs(x)
    tau = max(1.0, smooth_ms * 1e-3 * sample_rate)
    alpha = 1.0 / tau
    out = np.empty_like(rect)
    acc = 0.0
    for i in range(rect.size):
        acc += alpha * (rect[i] - acc)
        out[i] = acc
    return out


def rms(x: np.ndarray) -> float:
    x = np.asarray(x, dtype=np.float64)
    if x.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(x))))


def zero_crossing_rate(x: np.ndarray) -> float:
    x = np.asarray(x, dtype=np.float64)
    if x.size < 2:
        return 0.0
    return float(np.mean(np.abs(np.diff(np.signbit(x).astype(np.int8)))))


def spectral_features(
    x: np.ndarray, sample_rate: int
) -> tuple[float, float, np.ndarray]:
    """Возвращает (доминирующая частота, центроид, спектр амплитуд)."""
    x = np.asarray(x, dtype=np.float64)
    n = x.size
    if n < 8:
        return 0.0, 0.0, np.zeros(0)
    window = np.hanning(n)
    spectrum = np.abs(np.fft.rfft(x * window))
    freqs = np.fft.rfftfreq(n, d=1.0 / sample_rate)
    if spectrum.size <= 1:
        return 0.0, 0.0, spectrum
    peak_idx = int(np.argmax(spectrum[1:]) + 1)
    dominant = float(freqs[peak_idx])
    total = float(np.sum(spectrum[1:])) or 1.0
    centroid = float(np.sum(freqs[1:] * spectrum[1:]) / total)
    return dominant, centroid, spectrum
