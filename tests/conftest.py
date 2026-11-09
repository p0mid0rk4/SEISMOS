"""Общие фикстуры тестов SEISMOS."""

from __future__ import annotations

import pytest

from seismos.core.bus import EventBus
from seismos.core.config import Settings, SiteConfig
from seismos.core.engine import ProcessingEngine
from seismos.core.registry import Registry
from seismos.core.store import EventStore


@pytest.fixture
def site_config() -> SiteConfig:
    return SiteConfig(
        name="Тестовый объект",
        perimeter_length_m=400,
        sensors=[
            {"id": "S01", "name": "Датчик 1", "zone_id": "Z1", "chain_index": 0, "position_m": 0},
            {"id": "S02", "name": "Датчик 2", "zone_id": "Z1", "chain_index": 1, "position_m": 200},
            {"id": "S03", "name": "Датчик 3", "zone_id": "Z2", "chain_index": 2, "position_m": 300},
        ],
        zones=[
            {"id": "Z1", "name": "Север", "kind": "seismic", "length_m": 200},
            {"id": "Z2", "name": "Юг", "kind": "seismic", "length_m": 200},
        ],
        chains=[{"id": "CH1", "transport": "sim", "sensors": ["S01", "S02", "S03"]}],
    )


@pytest.fixture
def settings() -> Settings:
    return Settings(database_url="sqlite://:memory:", site_config="nonexistent.yaml")


@pytest.fixture
def registry(site_config: SiteConfig) -> Registry:
    return Registry(site_config)


@pytest.fixture
def store() -> EventStore:
    return EventStore(":memory:")


@pytest.fixture
def engine(settings: Settings, registry: Registry, store: EventStore) -> ProcessingEngine:
    return ProcessingEngine(settings, registry, store, EventBus())
