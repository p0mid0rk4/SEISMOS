"""Генератор синтетических сейсмических сигналов.

Используется для стендовых испытаний, автотестов и демонстрации
системы без физических геофонов. Формирует характерные сигнатуры
воздействий на периметр: шаги, группа людей, техника, подкоп,
перелаз, удар, метео-шум.
"""

from __future__ import annotations

import math

import numpy as np

from ..core.models import EventClass
from .geophone import GeophoneModel, GS20DXSpec


class SeismicSignalGenerator:
    """Генератор отсчётов «скорости грунта» (мкм/с) по типу воздействия."""

    def __init__(
        self,
        sample_rate: int = 1000,
        noise_microns: float = 0.8,
        seed: int | None = None,
        model: GeophoneModel | None = None,
    ) -> None:
        self.sample_rate = sample_rate
        self.noise_microns = noise_microns
        self._rng = np.random.default_rng(seed)
        self.model = model or GeophoneModel(GS20DXSpec(), sample_rate)

    # -- базовые примитивы ---------------------------------------------
    def background(self, duration_s: float) -> np.ndarray:
        n = int(duration_s * self.sample_rate)
        return self._rng.normal(0.0, self.noise_microns, size=n)

    def _wavelet(
        self, n: int, freq: float, decay: float, amp: float
    ) -> np.ndarray:
        t = np.arange(n) / self.sample_rate
        return amp * np.sin(2.0 * math.pi * freq * t) * np.exp(-decay * t)

    # -- сигнатуры воздействий -----------------------------------------
    def footstep(self, duration_s: float = 1.0, amp: float = 6.0, stride_hz: float = 2.0) -> np.ndarray:
        n = int(duration_s * self.sample_rate)
        out = np.zeros(n)
        period = 1.0 / stride_hz
        step_len = int(0.12 * self.sample_rate)
        t = 0.0
        while t < duration_s:
            start = int(t * self.sample_rate)
            if start + step_len < n:
                out[start:start + step_len] += self._wavelet(step_len, 28.0, 30.0, amp)
            t += period
        return out

    def group(self, duration_s: float = 4.0, amp: float = 9.0) -> np.ndarray:
        out = self.footstep(duration_s, amp * 0.7, stride_hz=3.0)
        out += self.footstep(duration_s, amp * 0.5, stride_hz=2.4)
        return out

    def vehicle(self, duration_s: float = 5.0, amp: float = 40.0) -> np.ndarray:
        n = int(duration_s * self.sample_rate)
        t = np.arange(n) / self.sample_rate
        # низкочастотный рокот с амплитудной модуляцией
        carrier = amp * np.sin(2.0 * math.pi * 11.0 * t)
        mod = 0.5 * (1.0 + np.sin(2.0 * math.pi * 0.8 * t))
        return carrier * mod

    def digging(self, duration_s: float = 3.0, amp: float = 25.0) -> np.ndarray:
        n = int(duration_s * self.sample_rate)
        out = np.zeros(n)
        strike_len = int(0.15 * self.sample_rate)
        t = 0.0
        while t < duration_s:
            start = int(t * self.sample_rate)
            if start + strike_len < n:
                out[start:start + strike_len] += self._wavelet(
                    strike_len, 45.0, 18.0, amp
                )
            t += 0.45
        return out

    def climb(self, duration_s: float = 2.0, amp: float = 20.0) -> np.ndarray:
        n = int(duration_s * self.sample_rate)
        out = np.zeros(n)
        impulse_len = int(0.08 * self.sample_rate)
        for start_frac in (0.1, 0.4, 0.7, 0.9):
            start = int(start_frac * n)
            if start + impulse_len < n:
                out[start:start + impulse_len] += self._wavelet(
                    impulse_len, 65.0, 40.0, amp
                )
        return out

    def impact(self, amp: float = 60.0) -> np.ndarray:
        n = int(0.2 * self.sample_rate)
        return self._wavelet(n, 95.0, 60.0, amp)

    def weather(self, duration_s: float = 2.0, amp: float = 3.0) -> np.ndarray:
        n = int(duration_s * self.sample_rate)
        return self._rng.normal(0.0, amp, size=n)

    def by_class(self, event_class: EventClass, duration_s: float = 2.0) -> np.ndarray:
        if event_class == EventClass.FOOTSTEP:
            return self.footstep(duration_s)
        if event_class == EventClass.GROUP:
            return self.group(duration_s)
        if event_class == EventClass.VEHICLE:
            return self.vehicle(duration_s)
        if event_class == EventClass.DIGGING:
            return self.digging(duration_s)
        if event_class == EventClass.CLIMB:
            return self.climb(duration_s)
        if event_class == EventClass.IMPACT:
            return self.impact()
        if event_class == EventClass.WEATHER:
            return self.weather(duration_s)
        return self.background(duration_s)

    # -- смешанный поток -------------------------------------------------
    def stream(
        self,
        duration_s: float = 10.0,
        events: list[tuple[float, EventClass]] | None = None,
    ) -> np.ndarray:
        """Сформировать непрерывный сигнал с заданными событиями.

        ``events`` — список пар (момент времени, с; класс воздействия).
        """
        n = int(duration_s * self.sample_rate)
        signal = self.background(duration_s)
        for t0, cls in events or []:
            event = self.by_class(cls)
            start = int(t0 * self.sample_rate)
            end = min(n, start + event.size)
            if start < n:
                signal[start:end] += event[: end - start]
        return signal

    def to_geophone_volts(self, ground_velocity_microns: np.ndarray) -> np.ndarray:
        """Перевести скорость грунта (мкм/с) в напряжение геофона (В)."""
        velocity_ms = np.asarray(ground_velocity_microns, dtype=np.float64) * 1e-6
        return self.model.apply_response(velocity_ms)
