"""Драйверы АЦП для узлов SEISMOS.

Поддерживаются:
* ``ADS1256`` — 24-битный АЦП (8 каналов), распространённый вариант
  построения модулей сбора на геофонах GS-20DX; подключается по SPI;
* ``SimulatedADC`` — программный источник отсчётов для стендов, тестов
  и демонстрации системы без физического оборудования.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np

try:  # pragma: no cover - зависит от платформы
    import spidev  # type: ignore
except Exception:  # noqa: BLE001
    spidev = None  # type: ignore


@dataclass
class ADCReading:
    """Один отсчёт АЦП."""

    channel: int
    raw: int
    volts: float
    ts: float = field(default_factory=time.time)


class ADC(Protocol):
    """Интерфейс АЦП."""

    def read(self, channel: int, count: int) -> np.ndarray: ...
    def close(self) -> None: ...


class ADS1256:
    """Драйвер 24-битного АЦП ADS1256 (SPI).

    Реализована работа через ``spidev`` с регистровым доступом. Класс
    пригоден для встраиваемых узлов на базе одноплатных компьютеров.
    """

    # Команды ADS1256
    CMD_WAKEUP = 0x00
    CMD_RDATA = 0x01
    CMD_SDATAC = 0x0F
    CMD_RREG = 0x10
    CMD_WREG = 0x50
    CMD_SYNC = 0xFC

    def __init__(
        self,
        bus: int = 0,
        device: int = 0,
        vref: float = 2.5,
        gain: float = 1.0,
        sample_rate: int = 1000,
        spi: object | None = None,
    ) -> None:
        self.vref = vref
        self.gain = gain
        self.sample_rate = sample_rate
        self._spi = spi
        if self._spi is None and spidev is not None:  # pragma: no cover - железо
            self._spi = spidev.SpiDev()
            self._spi.open(bus, device)
            self._spi.max_speed_hz = 1_920_000
            self._spi.mode = 0b01

    @property
    def lsb_volts(self) -> float:
        """Вес младшего разряда, В."""
        return (2.0 * self.vref / self.gain) / float(2**23 - 1)

    def _read_raw(self, channel: int) -> int:  # pragma: no cover - железо
        if self._spi is None:
            raise RuntimeError("SPI-устройство не инициализировано")
        # Установка мультиплексора и синхронизация
        mux = (channel & 0x0F) << 4
        self._spi.xfer2([self.CMD_WREG | 0x01, 0x00, mux])
        self._spi.xfer2([self.CMD_SYNC])
        self._spi.xfer2([self.CMD_WAKEUP])
        time.sleep(1.0 / self.sample_rate)
        resp = self._spi.xfer2([self.CMD_RDATA, 0x00, 0x00, 0x00])
        raw = (resp[1] << 16) | (resp[2] << 8) | resp[3]
        if raw & 0x800000:
            raw -= 0x1000000
        return raw

    def read(self, channel: int, count: int) -> np.ndarray:
        out = np.empty(count, dtype=np.float64)
        for i in range(count):
            raw = self._read_raw(channel)
            out[i] = raw * self.lsb_volts
        return out

    def close(self) -> None:  # pragma: no cover - железо
        if self._spi is not None:
            self._spi.close()


class SimulatedADC:
    """Программный АЦП для стендов и автотестов.

    Генерирует шум и, при необходимости, внешний сигнал, добавляемый
    через ``inject``. Позволяет воспроизводить поведение реального
    тракта без аппаратного обеспечения.
    """

    def __init__(
        self,
        sample_rate: int = 1000,
        noise_mv: float = 0.6,
        seed: int | None = None,
        vref: float = 2.5,
    ) -> None:
        self.sample_rate = sample_rate
        self.noise_mv = noise_mv
        self.vref = vref
        self._rng = np.random.default_rng(seed)
        self._pending: dict[int, np.ndarray] = {}

    def inject(self, channel: int, signal: np.ndarray) -> None:
        """Добавить внешний сигнал (В) к следующему чтению канала."""
        self._pending.setdefault(channel, np.zeros(0))
        self._pending[channel] = np.concatenate([self._pending[channel], signal])

    def read(self, channel: int, count: int) -> np.ndarray:
        noise = self._rng.normal(0.0, self.noise_mv / 1000.0, size=count)
        pending = self._pending.get(channel)
        if pending is not None and pending.size > 0:
            take = min(count, pending.size)
            noise[:take] += pending[:take]
            self._pending[channel] = pending[take:]
        return noise

    def close(self) -> None:
        self._pending.clear()


class ADCChain:
    """Последовательное подключение датчиков к одному АЦП.

    Датчики цепочки переключаются мультиплексором АЦП по каналам
    последовательно один за другим, что позволяет на одном узле
    обслуживать группу геофонов.
    """

    def __init__(self, adc: ADC, channels: list[int], sample_rate: int = 1000) -> None:
        self.adc = adc
        self.channels = channels
        self.sample_rate = sample_rate
        self._cursor = 0

    def next_channel(self) -> int:
        ch = self.channels[self._cursor % len(self.channels)]
        self._cursor += 1
        return ch

    def read_round(self, samples_per_channel: int = 1) -> dict[int, np.ndarray]:
        """Считать по одному блоку со всех каналов цепочки."""
        out: dict[int, np.ndarray] = {}
        for ch in self.channels:
            out[ch] = self.adc.read(ch, samples_per_channel)
        return out

    def close(self) -> None:
        self.adc.close()
