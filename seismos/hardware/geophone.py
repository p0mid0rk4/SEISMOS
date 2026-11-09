"""Модель сейсмического геофона GS-20DX.

GS-20DX — вертикальный геофон с собственной частотой 4.5 Гц, который
широко применяется в сейсморазведке и системах охраны периметра.
Здесь реализована его электромеханическая модель (передаточная функция
второго порядка) и перевод «напряжение → скорость смещения грунта».
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class GS20DXSpec:
    """Паспортные параметры геофона GS-20DX."""

    natural_frequency_hz: float = 4.5
    coil_resistance_ohm: float = 375.0
    sensitivity_v_per_m_s: float = 28.8
    open_circuit_damping: float = 0.56
    moving_mass_g: float = 11.0
    max_tilt_deg: float = 3.0
    spurious_frequency_hz: float = 240.0
    operating_temp_c: tuple[float, float] = (-40.0, 80.0)


class GeophoneModel:
    """Дискретная модель геофона (фильтр 2-го порядка).

    Передаточная функция по скорости:

        H(s) = S * s² / (s² + 2·ζ·ω₀·s + ω₀²)

    где ``ω₀ = 2π·f₀`` — собственная частота, ``ζ`` — коэффициент
    затухания, ``S`` — чувствительность (В/(м/с)). Модель применяется
    для нормировки и для генерации синтетических сигналов.
    """

    def __init__(self, spec: GS20DXSpec | None = None, sample_rate: int = 1000) -> None:
        self.spec = spec or GS20DXSpec()
        self.sample_rate = sample_rate

    def voltage_to_velocity(self, voltage: np.ndarray) -> np.ndarray:
        """Перевести напряжение с геофона в скорость смещения грунта (м/с)."""
        return np.asarray(voltage, dtype=np.float64) / self.spec.sensitivity_v_per_m_s

    def velocity_to_microns(self, velocity: np.ndarray) -> np.ndarray:
        """Скорость (м/с) в микрометры в секунду (мкм/с)."""
        return np.asarray(velocity, dtype=np.float64) * 1e6

    def magnitude_response(self, freqs_hz: np.ndarray) -> np.ndarray:
        """Амплитудно-частотная характеристика (нормированная)."""
        f = np.asarray(freqs_hz, dtype=np.float64)
        f0 = self.spec.natural_frequency_hz
        zeta = self.spec.open_circuit_damping
        s = 1j * f
        w0 = f0
        num = (s / w0) ** 2
        den = (s / w0) ** 2 + 2.0 * zeta * (s / w0) + 1.0
        return np.abs(num / den)

    def biquad_coefficients(self) -> tuple[np.ndarray, np.ndarray]:
        """Коэффициенты дискретного фильтра для моделирования отклика."""
        fs = self.sample_rate
        f0 = self.spec.natural_frequency_hz
        zeta = self.spec.open_circuit_damping
        w0 = 2.0 * math.pi * f0 / fs
        alpha = math.sin(w0) * zeta
        cos_w0 = math.cos(w0)
        b = np.array([1.0 + alpha, -2.0 * cos_w0, 1.0 - alpha])
        a = np.array([1.0, -2.0 * cos_w0, 1.0 - alpha])
        return b, a

    def apply_response(self, ground_velocity: np.ndarray) -> np.ndarray:
        """Смоделировать выход геофона для заданной скорости грунта."""
        b, a = self.biquad_coefficients()
        x = np.asarray(ground_velocity, dtype=np.float64)
        if x.size < 3:
            return x * self.spec.sensitivity_v_per_m_s
        y = np.zeros_like(x)
        for i in range(2, x.size):
            y[i] = (
                b[0] * x[i] + b[1] * x[i - 1] + b[2] * x[i - 2]
                - a[1] * y[i - 1] - a[2] * y[i - 2]
            )
        return y * self.spec.sensitivity_v_per_m_s

    def within_temperature(self, temp_c: float) -> bool:
        lo, hi = self.spec.operating_temp_c
        return lo <= temp_c <= hi

    def check_tilt(self, tilt_deg: float) -> bool:
        return abs(tilt_deg) <= self.spec.max_tilt_deg


GS20DX = GeophoneModel
