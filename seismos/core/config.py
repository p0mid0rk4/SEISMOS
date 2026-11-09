"""Конфигурация SEISMOS.

Настройки приложения читаются из переменных окружения с префиксом ``SEISMOS_``
и/или из YAML-файла объекта (``config/site.yaml``), который описывает датчики,
цепочки и зоны охраны.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .models import Zone

DEFAULT_SITE_PATH = Path("config/site.yaml")


class DetectionParams(BaseModel):
    """Параметры алгоритмов обнаружения."""

    sample_rate: int = 1000
    window_len: int = 1024
    hop: int = 256
    sta_len: int = 64
    lta_len: int = 1024
    trigger_ratio: float = 3.5
    release_ratio: float = 1.6
    min_duration_s: float = 0.08
    max_duration_s: float = 30.0
    cfar_alpha: float = 4.0
    cfar_guard: int = 4
    cfar_ref: int = 16
    noise_floor_alpha: float = 0.02
    band_low_hz: float = 5.0
    band_high_hz: float = 120.0
    debounce_s: float = 0.25


class ChainConfig(BaseModel):
    """Последовательная цепочка геофонов."""

    id: str
    transport: str = "sim"          # sim | udp | tcp | spidev | file
    sensors: list[str] = Field(default_factory=list)
    address: str | None = None      # host:port для udp/tcp
    path: str | None = None         # путь к файлу записи
    sample_rate: int = 1000
    enabled: bool = True


class SiteConfig(BaseModel):
    """Описание объекта охраны."""

    name: str = "SEISMOS Site"
    perimeter_length_m: float = 0.0
    sensors: list[dict[str, Any]] = Field(default_factory=list)
    zones: list[dict[str, Any]] = Field(default_factory=list)
    chains: list[ChainConfig] = Field(default_factory=list)

    def parsed_sensors(self) -> list[Sensor]:  # noqa: F821
        from .models import Sensor

        return [Sensor(**s) for s in self.sensors]

    def parsed_zones(self) -> list[Zone]:
        return [Zone(**z) for z in self.zones]


class Settings(BaseSettings):
    """Общие настройки приложения."""

    model_config = SettingsConfigDict(
        env_prefix="SEISMOS_",
        env_file=".env",
        extra="ignore",
    )

    site_config: str = str(DEFAULT_SITE_PATH)
    database_url: str = "sqlite:///data/seismos.db"
    data_dir: str = "data"
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"
    auth_token: str | None = None
    allow_sim: bool = True
    cors_origins: list[str] = Field(default_factory=lambda: ["*"])
    retention_days: int = 30
    max_events: int = 200_000
    detection: DetectionParams = Field(default_factory=DetectionParams)

    def load_site(self) -> SiteConfig:
        path = Path(self.site_config)
        if not path.exists():
            return SiteConfig()
        with path.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        return SiteConfig(**raw)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reload_settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()


def ensure_dirs(settings: Settings) -> None:
    Path(settings.data_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.data_dir, "recordings").mkdir(parents=True, exist_ok=True)
