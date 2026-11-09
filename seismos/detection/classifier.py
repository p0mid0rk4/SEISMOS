"""Классификация сейсмических событий по признакам сигнала.

Классификатор — экспертный (правиловый) и объяснимый: для каждого типа
воздействия задан эталонный профиль признаков (доминирующая частота,
длительность, амплитуда, число переходов через ноль). Итоговая оценка —
произведение гауссовых функций подобия по каждому признаку, что даёт
устойчивую к разбросу оценку уверенности и не требует обучения.

Экспертная модель выбрана намеренно: оператор должен понимать, почему
система отнесла событие к тому или иному классу, а поведение
классификатора должно быть предсказуемым на объекте.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..core.models import EventClass


@dataclass
class ClassifierFeatures:
    """Признаки события, используемые для классификации."""

    duration_s: float = 0.0
    peak: float = 0.0
    rms: float = 0.0
    dominant_hz: float = 0.0
    centroid_hz: float = 0.0
    zcr: float = 0.0
    ratio: float = 0.0
    band_energy: float = 0.0
    core_s: float = 0.0


# Эталонные профили: (f0_Гц, σf, длит_с, σдлит, пик_мкм/с, σпик, вес).
# Число переходов через ноль используется как вспомогательный признак
# при равных оценках, но не входит в произведение (он сильно зависит
# от полосы фильтра и потому малоинформативен для тонких различений).
_PROFILES: dict[EventClass, tuple[float, ...]] = {
    EventClass.FOOTSTEP: (25.0, 7.0, 2.50, 1.80, 6.0, 4.0, 1.00),
    EventClass.GROUP: (23.0, 7.0, 4.50, 3.00, 13.0, 9.0, 1.00),
    EventClass.VEHICLE: (11.0, 4.0, 5.00, 3.50, 34.0, 22.0, 1.10),
    EventClass.DIGGING: (47.0, 10.0, 3.00, 2.00, 24.0, 18.0, 1.00),
    EventClass.CLIMB: (62.0, 10.0, 0.90, 0.60, 11.0, 8.0, 1.00),
    EventClass.IMPACT: (90.0, 22.0, 0.15, 0.10, 55.0, 35.0, 1.10),
    EventClass.TAMPER: (70.0, 15.0, 0.45, 0.35, 6.5, 5.0, 1.00),
    EventClass.WEATHER: (33.0, 22.0, 0.30, 0.22, 3.0, 2.0, 1.00),
}

# Обострение различий между близкими оценками.
_SHARPNESS = 1.7


def _gauss(x: float, mu: float, sigma: float) -> float:
    if sigma <= 1e-9:
        return 1.0 if abs(x - mu) < 1e-9 else 0.0
    return math.exp(-0.5 * ((x - mu) / sigma) ** 2)


class Classifier:
    """Правиловый классификатор с оценкой уверенности."""

    def __init__(self, min_confidence: float = 0.30) -> None:
        self.min_confidence = min_confidence

    def _vector(self, feat: ClassifierFeatures) -> tuple[float, float, float]:
        freq = feat.dominant_hz if feat.dominant_hz > 0 else feat.centroid_hz
        # Длительность активной части события: хвост удержания детектора
        # не должен влиять на классификацию.
        dur = feat.core_s if feat.core_s > 0 else feat.duration_s
        return (freq, dur, feat.peak)

    def scores(self, feat: ClassifierFeatures) -> dict[EventClass, float]:
        """Оценки соответствия события каждому классу (0..1)."""
        freq, dur, peak = self._vector(feat)
        out: dict[EventClass, float] = {}
        for cls, p in _PROFILES.items():
            f0, sf, d0, sd, a0, sa, w = p
            sim = (
                _gauss(freq, f0, sf)
                * _gauss(dur, d0, sd)
                * _gauss(peak, a0, sa)
            )
            out[cls] = min(1.0, (sim ** (1.0 / 3.0)) * w)
        return out

    def classify(self, feat: ClassifierFeatures) -> tuple[EventClass, float]:
        """Вернуть наиболее вероятный класс и уверенность [0..1]."""
        if feat.duration_s <= 0.0 and feat.peak <= 0.0:
            return EventClass.NONE, 0.0

        scores = self.scores(feat)
        best_cls, best = max(scores.items(), key=lambda kv: kv[1])
        best = min(1.0, best ** _SHARPNESS)
        if best < self.min_confidence:
            return EventClass.UNKNOWN, best
        return best_cls, best


# Соответствие класса события уровню тревоги (0 — шум, 3 — проникновение).
CLASS_LEVEL: dict[EventClass, int] = {
    EventClass.NONE: 0,
    EventClass.WEATHER: 0,
    EventClass.FOOTSTEP: 1,
    EventClass.GROUP: 2,
    EventClass.VEHICLE: 3,
    EventClass.DIGGING: 3,
    EventClass.CLIMB: 3,
    EventClass.IMPACT: 2,
    EventClass.TAMPER: 3,
    EventClass.UNKNOWN: 1,
}
