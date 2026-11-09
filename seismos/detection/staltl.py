"""Обнаружение сейсмических событий: STA/LTA и адаптивный порог CFAR."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import numpy as np

from .dsp import BandPass, spectral_features, zero_crossing_rate


@dataclass
class DetectorResult:
    """Результат работы детектора на одном блоке отсчётов."""

    triggered: bool = False
    ended: bool = False
    ratio: float = 0.0
    peak: float = 0.0
    rms: float = 0.0
    duration_s: float = 0.0
    dominant_hz: float = 0.0
    centroid_hz: float = 0.0
    zcr: float = 0.0
    features: dict[str, float] = field(default_factory=dict)


class STALTA:
    """Классический детектор STA/LTA с рекурсивными окнами."""

    def __init__(self, sta_len: int, lta_len: int) -> None:
        self.sta_len = max(1, sta_len)
        self.lta_len = max(2, lta_len)
        self._sta = 0.0
        self._lta = 0.0
        self._initialized = False

    def update(self, value: float) -> float:
        a_sta = 1.0 / self.sta_len
        a_lta = 1.0 / self.lta_len
        if not self._initialized:
            self._sta = value
            self._lta = value
            self._initialized = True
        self._sta += a_sta * (value - self._sta)
        self._lta += a_lta * (value - self._lta)
        if self._lta <= 1e-12:
            return 0.0
        return self._sta / self._lta

    @property
    def sta(self) -> float:
        return self._sta

    @property
    def lta(self) -> float:
        return self._lta

    def reset(self) -> None:
        self._sta = self._lta = 0.0
        self._initialized = False


class CfarDetector:
    """Адаптивный порог (Cell-Averaging CFAR) для нестационарного шума.

    Порог вычисляется как ``alpha * оценка_шума`` по опорным отсчётам
    вокруг проверяемой ячейки, что позволяет сохранять постоянную
    вероятность ложной тревоги при изменении уровня фона (ветер, дождь).
    """

    def __init__(self, ref: int = 48, guard: int = 8, alpha: float = 4.0) -> None:
        self.ref = max(4, ref)
        self.guard = max(0, guard)
        self.alpha = alpha
        self._history: deque[float] = deque(maxlen=self.ref * 2 + 2)

    def update(self, value: float) -> tuple[bool, float]:
        self._history.append(value)
        if len(self._history) < self.ref + self.guard + 1:
            return False, 0.0
        hist = list(self._history)
        cell = hist[-1]
        end_ref = len(hist) - 1 - self.guard
        start_ref = max(0, end_ref - self.ref)
        ref_cells = hist[start_ref:end_ref]
        if not ref_cells:
            return False, 0.0
        noise = float(np.mean(ref_cells))
        ratio = cell / noise if noise > 1e-12 else 0.0
        return cell > self.alpha * noise, ratio

    def reset(self) -> None:
        self._history.clear()


class SeismicDetector:
    """Полный конвейер обнаружения для одного канала геофона.

    Последовательность: полосовая фильтрация → СКЗ по окнам → STA/LTA →
    CFAR → выделение признаков события для классификации.
    """

    def __init__(
        self,
        sample_rate: int = 1000,
        sta_len: int = 64,
        lta_len: int = 1024,
        trigger_ratio: float = 3.5,
        release_ratio: float = 1.6,
        min_duration_s: float = 0.08,
        max_duration_s: float = 30.0,
        band_low_hz: float = 5.0,
        band_high_hz: float = 120.0,
        cfar_alpha: float = 4.0,
        cfar_ref: int = 16,
        cfar_guard: int = 4,
        frame_len: int = 64,
        hold_s: float = 0.6,
    ) -> None:
        self.sample_rate = sample_rate
        self.trigger_ratio = trigger_ratio
        self.release_ratio = release_ratio
        self.min_duration_s = min_duration_s
        self.max_duration_s = max_duration_s
        self.frame_len = frame_len
        self.band = BandPass(sample_rate, band_low_hz, band_high_hz)
        # sta_len/lta_len заданы в отсчётах; переводим в кадры обработки
        sta_frames = max(1, round(sta_len / frame_len))
        lta_frames = max(2, round(lta_len / frame_len))
        self.sta_lta = STALTA(sta_frames, lta_frames)
        self.cfar = CfarDetector(cfar_ref, cfar_guard, cfar_alpha)
        # Удержание события открытым после падения сигнала: склеивает
        # разрозненные импульсы одного воздействия (шаги, рокот техники)
        # в единое событие и снижает дробление журнала.
        self._hold_frames = max(1, round(hold_s * sample_rate / frame_len))
        self._hold = 0
        self._active = False
        self._event_start_sample = 0
        self._total_samples = 0
        self._peak = 0.0
        self._trigger_ratio = 0.0
        self._buffer: list[float] = []

    def process(self, block: np.ndarray) -> DetectorResult:
        """Обработать блок отсчётов и вернуть накопленный результат."""
        block = np.asarray(block, dtype=np.float64)
        if block.size == 0:
            return DetectorResult()
        filtered = self.band.process(block)
        result = DetectorResult()

        for start in range(0, filtered.size, self.frame_len):
            chunk = filtered[start:start + self.frame_len]
            if chunk.size == 0:
                break
            level = float(np.sqrt(np.mean(np.square(chunk))))
            peak = float(np.max(np.abs(chunk)))
            ratio = self.sta_lta.update(level)
            cfar_hit, _ = self.cfar.update(level)
            self._total_samples += chunk.size

            if not self._active:
                if ratio >= self.trigger_ratio and cfar_hit:
                    self._active = True
                    self._hold = self._hold_frames
                    self._event_start_sample = self._total_samples - chunk.size
                    self._peak = peak
                    self._trigger_ratio = ratio
                    self._buffer = list(chunk)
                    result.triggered = True
                    result.ratio = ratio
                    result.peak = peak
            else:
                self._buffer.extend(chunk.tolist())
                self._peak = max(self._peak, peak)
                self._trigger_ratio = max(self._trigger_ratio, ratio)
                duration = (self._total_samples - self._event_start_sample) / self.sample_rate
                if ratio > self.release_ratio:
                    self._hold = self._hold_frames
                else:
                    self._hold -= 1
                if (self._hold <= 0 and duration >= self.min_duration_s) \
                        or duration >= self.max_duration_s:
                    self._finish(result, duration)
        return result

    def _finish(self, result: DetectorResult, duration: float) -> None:
        buf = np.asarray(self._buffer, dtype=np.float64)
        # Признаки считаем по энергетическому ядру события, а не по всему
        # буферу: хвост удержания содержит фоновый шум и искажает спектр
        # коротких импульсов (например, удара по ограждению).
        core = self._energetic_core(buf)
        dom, centroid, spectrum = spectral_features(core, self.sample_rate)
        zcr = zero_crossing_rate(core)
        result.ended = True
        result.duration_s = duration
        result.peak = self._peak
        result.ratio = self._trigger_ratio
        result.dominant_hz = dom
        result.centroid_hz = centroid
        result.zcr = zcr
        result.rms = float(np.sqrt(np.mean(np.square(buf)))) if buf.size else 0.0
        result.features = {
            "duration_s": duration,
            "core_s": core.size / self.sample_rate,
            "zcr": zcr,
            "dominant_hz": dom,
            "centroid_hz": centroid,
            "band_energy": float(np.sum(np.square(spectrum))) if spectrum.size else 0.0,
            "peak": self._peak,
            "rms": result.rms,
        }
        self._active = False
        self._hold = 0
        self._peak = 0.0
        self._trigger_ratio = 0.0
        self._buffer = []

    def _energetic_core(self, buf: np.ndarray) -> np.ndarray:
        """Выделить участок сигнала выше порога (энергетическое ядро)."""
        if buf.size < 8:
            return buf
        magnitude = np.abs(buf)
        peak = float(np.max(magnitude))
        if peak <= 1e-9:
            return buf
        mask = magnitude >= 0.25 * peak
        if not np.any(mask):
            return buf
        idx = np.flatnonzero(mask)
        start = max(0, int(idx[0]) - 4)
        stop = min(buf.size, int(idx[-1]) + 5)
        core = buf[start:stop]
        return core if core.size >= 8 else buf

    @property
    def active(self) -> bool:
        return self._active

    @property
    def noise_level(self) -> float:
        return self.sta_lta.lta
