"""Узел сбора данных SEISMOS: АЦП + Ethernet с питанием PoE.

Каждый узел обслуживает группу геофонов GS-20DX, оцифровывает сигнал
и передаёт отсчёты по сети. Узел получает питание по PoE (IEEE 802.3af/at),
что снимает необходимость прокладки отдельного питания по периметру.
"""

from __future__ import annotations

import asyncio
import json
import socket
import struct
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .adc import ADC, SimulatedADC
from .geophone import GeophoneModel, GS20DXSpec

# Формат пакета данных узла: magic(4) + sensor_id(2) + seq(4) + ts(8) + n(2) + отсчёты(int16)
PACKET_MAGIC = b"SMS1"
PACKET_HEADER = struct.Struct("!4sHIdH")


@dataclass
class NodeConfig:
    """Конфигурация узла сбора."""

    node_id: str
    address: str = "0.0.0.0"
    port: int = 4789
    sample_rate: int = 1000
    channels: list[int] = field(default_factory=lambda: [0])
    sensor_ids: list[str] = field(default_factory=list)
    poe_class: str = "802.3at"
    gain_db: float = 0.0
    spec: GS20DXSpec = field(default_factory=GS20DXSpec)


class SensorNode:
    """Узел сбора данных на геофонах GS-20DX.

    Отвечает за оцифровку сигналов группы датчиков, нормировку по
    чувствительности геофона, формирование пакетов и их передачу в
    сеть (UDP). Также поддерживает локальный режим (без сети) для
    стендовых испытаний.
    """

    def __init__(
        self,
        config: NodeConfig,
        adc: ADC | None = None,
        model: GeophoneModel | None = None,
    ) -> None:
        self.config = config
        self.adc = adc or SimulatedADC(sample_rate=config.sample_rate)
        self.model = model or GeophoneModel(config.spec, config.sample_rate)
        self._seq = 0
        self._sock: socket.socket | None = None
        self._online = False
        self.last_seen = time.time()

    # -- сеть -----------------------------------------------------------
    def open(self) -> None:
        if self._sock is None:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    def close(self) -> None:
        if self._sock is not None:
            self._sock.close()
            self._sock = None
        self.adc.close()

    @property
    def online(self) -> bool:
        return self._online

    # -- оцифровка ------------------------------------------------------
    def sample_channel(self, channel_index: int, count: int) -> np.ndarray:
        """Считать ``count`` отсчётов и перевести их в мкм/с."""
        channel = self.config.channels[channel_index % len(self.config.channels)]
        volts = self.adc.read(channel, count)
        velocity = self.model.voltage_to_velocity(volts)
        return self.model.velocity_to_microns(velocity)

    def sample_all(self, count: int) -> dict[str, np.ndarray]:
        """Считать блок со всех датчиков узла (последовательно по цепочке)."""
        out: dict[str, np.ndarray] = {}
        for idx, sensor_id in enumerate(self.config.sensor_ids):
            out[sensor_id] = self.sample_channel(idx, count)
        return out

    # -- упаковка -------------------------------------------------------
    def pack(self, sensor_index: int, samples: np.ndarray) -> bytes:
        self._seq = (self._seq + 1) & 0xFFFFFFFF
        clipped = np.clip(samples, -32768, 32767).astype(np.int16)
        header = PACKET_HEADER.pack(
            PACKET_MAGIC, sensor_index & 0xFFFF, self._seq, time.time(),
            int(clipped.size),
        )
        return header + clipped.tobytes()

    def send(self, sensor_index: int, samples: np.ndarray) -> None:
        self.open()
        assert self._sock is not None
        self._sock.sendto(
            self.pack(sensor_index, samples),
            (self.config.address, self.config.port),
        )
        self.last_seen = time.time()
        self._online = True

    async def run(self, block: int = 128, interval: float | None = None) -> None:
        """Цикл сбора и передачи данных (асинхронный)."""
        interval = interval or block / self.config.sample_rate
        while True:
            data = self.sample_all(block)
            for idx, sensor_id in enumerate(self.config.sensor_ids):
                _ = sensor_id
                self.send(idx, data[sensor_id])
            await asyncio.sleep(interval)

    def status(self) -> dict[str, Any]:
        return {
            "node_id": self.config.node_id,
            "address": self.config.address,
            "port": self.config.port,
            "poe_class": self.config.poe_class,
            "sample_rate": self.config.sample_rate,
            "sensors": self.config.sensor_ids,
            "online": self._online,
            "last_seen": self.last_seen,
            "seq": self._seq,
        }


def unpack_packet(packet: bytes) -> tuple[int, int, float, np.ndarray]:
    """Разобрать пакет узла в (sensor_index, seq, ts, отсчёты)."""
    header_size = PACKET_HEADER.size
    if len(packet) < header_size:
        raise ValueError("Слишком короткий пакет")
    magic, sensor_index, seq, ts, n = PACKET_HEADER.unpack(packet[:header_size])
    if magic != PACKET_MAGIC:
        raise ValueError("Неверная сигнатура пакета")
    payload = packet[header_size:header_size + n * 2]
    samples = np.frombuffer(payload, dtype="<i2").astype(np.float64)
    return sensor_index, seq, ts, samples


class UDPReceiver:
    """Приёмник пакетов от узлов сбора (UDP)."""

    def __init__(self, host: str = "0.0.0.0", port: int = 4789) -> None:
        self.host = host
        self.port = port
        self._sock: socket.socket | None = None

    def open(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.host, self.port))
        self._sock.setblocking(False)

    def close(self) -> None:
        if self._sock is not None:
            self._sock.close()
            self._sock = None

    def recv(self, timeout: float = 0.0) -> list[tuple[str, bytes]]:
        """Принять доступные пакеты: список (адрес, данные)."""
        if self._sock is None:
            self.open()
        assert self._sock is not None
        packets: list[tuple[str, bytes]] = []
        deadline = time.time() + timeout
        while True:
            try:
                data, addr = self._sock.recvfrom(65535)
                packets.append((addr[0], data))
            except BlockingIOError:
                if time.time() >= deadline:
                    break
                time.sleep(0.002)
            except OSError:
                break
        return packets

    def describe(self) -> str:
        return json.dumps({"host": self.host, "port": self.port})
