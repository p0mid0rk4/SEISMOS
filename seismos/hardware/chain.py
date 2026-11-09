"""Последовательное чтение цепочки геофонов и мультиплексирование каналов.

В системе SEISMOS датчики одной цепочки опрашиваются последовательно
один за другим. ``ChainReader`` реализует этот режим: циклически
считывает блоки со всех датчиков цепочки и формирует единый поток
``ChainSample``, который далее поступает в движок обнаружения.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field

import numpy as np

from .adc import ADCChain
from .node import SensorNode


@dataclass
class ChainSample:
    """Блок отсчётов одного датчика цепочки."""

    sensor_id: str
    samples: np.ndarray
    ts: float = field(default_factory=time.time)
    seq: int = 0


class ChainReader:
    """Последовательный опрос датчиков одной цепочки.

    Работает с любым источником: узлом сбора (``SensorNode``) или
    напрямую с АЦП (``ADCChain``). Порядок обхода задаётся списком
    ``sensor_ids`` и соответствует физической раскладке геофонов.
    """

    def __init__(
        self,
        chain_id: str,
        sensor_ids: list[str],
        node: SensorNode | None = None,
        adc_chain: ADCChain | None = None,
        block: int = 128,
        sample_rate: int = 1000,
    ) -> None:
        if node is None and adc_chain is None:
            raise ValueError("Нужен источник данных: node или adc_chain")
        self.chain_id = chain_id
        self.sensor_ids = sensor_ids
        self.node = node
        self.adc_chain = adc_chain
        self.block = block
        self.sample_rate = sample_rate
        self._seq = 0

    def read_once(self) -> list[ChainSample]:
        """Один полный обход цепочки: по блоку с каждого датчика."""
        out: list[ChainSample] = []
        if self.node is not None:
            data = self.node.sample_all(self.block)
            for sensor_id in self.sensor_ids:
                out.append(ChainSample(sensor_id, data[sensor_id], time.time(), self._seq))
                self._seq += 1
            return out

        assert self.adc_chain is not None
        for idx, sensor_id in enumerate(self.sensor_ids):
            channel = self.adc_chain.channels[idx % len(self.adc_chain.channels)]
            samples = self.adc_chain.adc.read(channel, self.block)
            out.append(ChainSample(sensor_id, samples, time.time(), self._seq))
            self._seq += 1
        return out

    def stream(self, cycles: int | None = None) -> Iterator[list[ChainSample]]:
        """Синхронный поток обходов цепочки."""
        count = 0
        interval = self.block / self.sample_rate
        while cycles is None or count < cycles:
            yield self.read_once()
            count += 1
            time.sleep(interval)

    async def astream(self, cycles: int | None = None) -> AsyncIterator[list[ChainSample]]:
        """Асинхронный поток обходов цепочки."""
        import asyncio

        count = 0
        interval = self.block / self.sample_rate
        while cycles is None or count < cycles:
            yield self.read_once()
            count += 1
            await asyncio.sleep(interval)

    def describe(self) -> dict[str, object]:
        return {
            "chain_id": self.chain_id,
            "sensors": self.sensor_ids,
            "block": self.block,
            "sample_rate": self.sample_rate,
            "source": "node" if self.node is not None else "adc",
        }


def multiplex(chains: list[ChainReader], cycles: int = 1) -> list[ChainSample]:
    """Считать по одному обходу всех цепочек и слить результаты."""
    merged: list[ChainSample] = []
    for _ in range(cycles):
        for chain in chains:
            merged.extend(chain.read_once())
    return merged
