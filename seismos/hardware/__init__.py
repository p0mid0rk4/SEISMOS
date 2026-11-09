"""Аппаратный слой SEISMOS: геофоны GS-20DX, АЦП, узлы Ethernet/PoE."""

from .adc import ADS1256, ADCReading, SimulatedADC
from .chain import ChainReader, ChainSample
from .geophone import GS20DX, GeophoneModel
from .node import NodeConfig, SensorNode
from .simulator import SeismicSignalGenerator

__all__ = [
    "ADS1256",
    "GS20DX",
    "ADCReading",
    "ChainReader",
    "ChainSample",
    "GeophoneModel",
    "NodeConfig",
    "SeismicSignalGenerator",
    "SensorNode",
    "SimulatedADC",
]
