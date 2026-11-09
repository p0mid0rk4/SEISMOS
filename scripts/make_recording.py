#!/usr/bin/env python3
"""Генерация синтетической записи сигнала для стендовых испытаний.

Формирует непрерывный сигнал с заданными воздействиями и сохраняет его в
формате .npy (скорость грунта, мкм/с). Полученный файл можно использовать
для отладки детектора и классификатора без оборудования.

Пример:
    python scripts/make_recording.py --duration 60 --out data/recordings/demo.npy
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seismos.core.models import EventClass  # noqa: E402
from seismos.hardware.simulator import SeismicSignalGenerator  # noqa: E402

SCENARIO = [
    (5.0, EventClass.FOOTSTEP),
    (12.0, EventClass.GROUP),
    (22.0, EventClass.VEHICLE),
    (34.0, EventClass.DIGGING),
    (44.0, EventClass.CLIMB),
    (52.0, EventClass.IMPACT),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Генерация записи сигнала СЕЙСМОС")
    parser.add_argument("--duration", type=float, default=60.0, help="Длительность, с")
    parser.add_argument("--sample-rate", type=int, default=1000, help="Частота, Гц")
    parser.add_argument("--seed", type=int, default=42, help="Зерно генератора")
    parser.add_argument("--out", default="data/recordings/demo.npy", help="Путь вывода")
    args = parser.parse_args()

    gen = SeismicSignalGenerator(sample_rate=args.sample_rate, seed=args.seed)
    signal = gen.stream(duration_s=args.duration, events=SCENARIO)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    np.save(out, signal)

    peak = float(np.abs(signal).max())
    print(f"Записано {signal.size} отсчётов ({args.duration:.1f} с) в {out}")
    print(f"Пиковая амплитуда: {peak:.1f} мкм/с")
    print("Сценарий:")
    for t0, cls in SCENARIO:
        print(f"  {t0:5.1f} с — {cls.value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
