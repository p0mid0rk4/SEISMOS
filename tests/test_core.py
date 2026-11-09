"""Тесты реестра, хранилища и движка обработки."""

from __future__ import annotations

import time

import numpy as np
import pytest

from seismos.core.bus import EventBus
from seismos.core.engine import ProcessingEngine
from seismos.core.models import (
    Alarm,
    AlarmState,
    DetectionEvent,
    EventClass,
    EventKind,
    EventLevel,
    SystemState,
)
from seismos.core.registry import Registry
from seismos.core.store import EventStore
from seismos.hardware.chain import ChainSample
from seismos.hardware.simulator import SeismicSignalGenerator


def test_registry_builds_from_config(registry: Registry):
    assert len(registry.sensors) == 3
    assert len(registry.zones) == 2
    assert len(registry.chains["CH1"]) == 3


def test_registry_zone_sensor_ids(registry: Registry):
    assert set(registry.zone_sensor_ids("Z1")) == {"S01", "S02"}
    assert registry.zone_sensor_ids("Z2") == ["S03"]


def test_registry_neighbors_follow_chain_order(registry: Registry):
    neighbors = registry.neighbor_sensors("S02")
    assert {s.id for s in neighbors} == {"S01", "S03"}
    assert registry.neighbor_sensors("S01")[0].id == "S02"


def test_registry_summary_counts(registry: Registry):
    registry.mark_online("S01", True)
    summary = registry.summary()
    assert summary["sensors_total"] == 3
    assert summary["sensors_online"] == 1
    assert summary["zones_armed"] == 2


@pytest.mark.asyncio
async def test_store_add_and_query_events(store: EventStore):
    await store.init()
    ev = DetectionEvent(
        sensor_id="S01", zone_id="Z1", kind=EventKind.ALARM,
        level=EventLevel.ALARM, event_class=EventClass.FOOTSTEP, confidence=0.8,
    )
    await store.add_event(ev)
    rows = await store.query_events()
    assert len(rows) == 1
    assert rows[0]["event_class"] == "footstep"
    assert store.recent(10)[0].id == ev.id
    await store.close()


@pytest.mark.asyncio
async def test_store_alarm_lifecycle(store: EventStore):
    await store.init()
    alarm = Alarm(sensor_id="S01", zone_id="Z1", event_class=EventClass.VEHICLE)
    await store.add_alarm(alarm)
    assert await store.count_alarms(AlarmState.ACTIVE) == 1
    alarm.state = AlarmState.ACKNOWLEDGED
    await store.add_alarm(alarm)
    assert await store.count_alarms(AlarmState.ACTIVE) == 0
    rows = await store.query_alarms(state="acknowledged")
    assert len(rows) == 1
    await store.close()


@pytest.mark.asyncio
async def test_store_stats_and_purge(store: EventStore):
    await store.init()
    for i in range(3):
        await store.add_event(DetectionEvent(
            sensor_id="S01", zone_id="Z1", level=EventLevel.ALARM,
            event_class=EventClass.FOOTSTEP, ts=time.time() - i * 86400 * 10,
        ))
    stats = await store.stats()
    assert stats["events_total"] == 3
    removed = await store.purge_older_than(1)
    assert removed == 2
    await store.close()


@pytest.mark.asyncio
async def test_engine_arms_and_disarms(engine: ProcessingEngine):
    await engine.store.init()
    await engine.arm("tester")
    assert engine.state == SystemState.ARMED
    assert all(z.armed for z in engine.registry.zones.values())
    await engine.disarm("tester")
    assert engine.state == SystemState.DISARMED
    await engine.store.close()


@pytest.mark.asyncio
async def test_engine_creates_alarm_on_strong_event(engine: ProcessingEngine):
    await engine.store.init()
    await engine.arm("tester")
    event = DetectionEvent(
        sensor_id="S01", zone_id="Z1", kind=EventKind.INTRUSION,
        level=EventLevel.INTRUSION, event_class=EventClass.VEHICLE, confidence=0.9,
    )
    await engine.handle_event(event)
    alarms = engine.active_alarms()
    assert len(alarms) == 1
    assert engine.state == SystemState.ALARM

    alarm = alarms[0]
    acked = await engine.acknowledge(alarm.id, "operator", "принято")
    assert acked is not None
    assert acked.state == AlarmState.ACKNOWLEDGED
    assert engine.state == SystemState.ARMED
    await engine.store.close()


@pytest.mark.asyncio
async def test_engine_no_alarm_when_disarmed(engine: ProcessingEngine):
    await engine.store.init()
    event = DetectionEvent(
        sensor_id="S01", zone_id="Z1", level=EventLevel.ALARM,
        event_class=EventClass.CLIMB, confidence=0.9,
    )
    await engine.handle_event(event)
    assert engine.active_alarms() == []
    await engine.store.close()


@pytest.mark.asyncio
async def test_engine_ignores_quiet_background(engine: ProcessingEngine):
    await engine.store.init()
    gen = SeismicSignalGenerator(sample_rate=1000, noise_microns=0.5, seed=7)
    bg = gen.background(3.0)
    produced = []
    for start in range(0, bg.size, 128):
        sample = ChainSample("S01", bg[start:start + 128], time.time(), 0)
        produced.extend(engine.ingest(sample))
    assert produced == []
    await engine.store.close()


@pytest.mark.asyncio
async def test_engine_detects_footstep_end_to_end(engine: ProcessingEngine):
    await engine.store.init()
    await engine.arm("tester")
    gen = SeismicSignalGenerator(sample_rate=1000, seed=8)
    signal = np.concatenate([gen.background(2.5), gen.footstep(2.0), gen.background(2.0)])
    produced = []
    for start in range(0, signal.size, 128):
        sample = ChainSample("S01", signal[start:start + 128], time.time(), 0)
        for event in engine.ingest(sample):
            produced.append(event)
            await engine.handle_event(event)
    assert produced, "Ожидалось обнаружение шагов"
    assert produced[0].zone_id == "Z1"
    await engine.store.close()


def test_event_bus_publishes_to_subscribers():
    bus = EventBus()
    received = []
    queue = None

    import asyncio

    async def run():
        nonlocal queue
        queue = await bus.subscribe()
        bus.publish("event", {"id": "1"})
        msg = await asyncio.wait_for(queue.get(), timeout=1.0)
        received.append(msg)
        await bus.unsubscribe(queue)

    asyncio.run(run())
    assert received[0]["topic"] == "event"
    assert received[0]["payload"]["id"] == "1"
