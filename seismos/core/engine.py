"""Движок обработки SEISMOS.

Связывает источник данных (узел сбора/АЦП) с конвейером обнаружения,
ведёт журнал событий, формирует тревоги, управляет режимом охраны и
рассылает данные подписчикам через шину событий.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict

from ..core.bus import EventBus
from ..core.config import Settings
from ..core.models import (
    Alarm,
    AlarmState,
    DetectionEvent,
    EventKind,
    EventLevel,
    SystemState,
    SystemStatus,
)
from ..core.registry import Registry
from ..core.store import EventStore
from ..detection.classifier import CLASS_LEVEL, Classifier, ClassifierFeatures
from ..detection.staltl import DetectorResult, SeismicDetector
from ..hardware.chain import ChainReader, ChainSample

_LEVEL_TO_KIND = {
    0: EventKind.NOISE,
    1: EventKind.WARNING,
    2: EventKind.ALARM,
    3: EventKind.INTRUSION,
}


class ProcessingEngine:
    """Обработчик сейсмических данных системы контроля периметра."""

    def __init__(
        self,
        settings: Settings,
        registry: Registry,
        store: EventStore,
        bus: EventBus,
    ) -> None:
        self.settings = settings
        self.registry = registry
        self.store = store
        self.bus = bus
        self.classifier = Classifier()
        self._detectors: dict[str, SeismicDetector] = {}
        self._last_event_ts: dict[str, float] = defaultdict(float)
        self._alarms: dict[str, Alarm] = {}
        self._state = SystemState.DISARMED
        self._started_at = time.time()
        self._events_total = 0
        self._tasks: set[asyncio.Task[None]] = set()
        self._running = False

    # -- детекторы ------------------------------------------------------
    def detector_for(self, sensor_id: str) -> SeismicDetector:
        det = self._detectors.get(sensor_id)
        if det is None:
            params = self.settings.detection
            det = SeismicDetector(
                sample_rate=params.sample_rate,
                sta_len=params.sta_len,
                lta_len=params.lta_len,
                trigger_ratio=params.trigger_ratio,
                release_ratio=params.release_ratio,
                min_duration_s=params.min_duration_s,
                max_duration_s=params.max_duration_s,
                band_low_hz=params.band_low_hz,
                band_high_hz=params.band_high_hz,
                cfar_alpha=params.cfar_alpha,
                cfar_ref=params.cfar_ref,
                cfar_guard=params.cfar_guard,
            )
            self._detectors[sensor_id] = det
        return det

    # -- режим охраны ---------------------------------------------------
    @property
    def state(self) -> SystemState:
        return self._state

    async def set_state(self, state: SystemState, user: str = "system") -> None:
        self._state = state
        await self.store.audit(user, "set_state", state.value)
        self.bus.publish("state", {"state": state.value, "ts": time.time()})

    async def arm(self, user: str = "operator") -> None:
        for zone in self.registry.zones.values():
            zone.armed = True
        await self.set_state(SystemState.ARMED, user)

    async def disarm(self, user: str = "operator") -> None:
        for zone in self.registry.zones.values():
            zone.armed = False
        await self.set_state(SystemState.DISARMED, user)

    # -- приём и обработка ---------------------------------------------
    def ingest(self, sample: ChainSample) -> list[DetectionEvent]:
        """Обработать блок отсчётов одного датчика."""
        sensor = self.registry.sensor(sample.sensor_id)
        if sensor is None or not sensor.enabled:
            return []
        sensor.online = True
        sensor.last_seen = sample.ts
        detector = self.detector_for(sample.sensor_id)
        result = detector.process(sample.samples)
        events: list[DetectionEvent] = []
        if result.triggered and not result.ended:
            return events
        if result.ended:
            event = self._build_event(sensor.id, sensor.zone_id, result)
            if event is not None:
                events.append(event)
        return events

    def _build_event(
        self, sensor_id: str, zone_id: str, result: DetectorResult
    ) -> DetectionEvent | None:
        feat = result.features or {}
        cls, confidence = self.classifier.classify(
            ClassifierFeatures(
                duration_s=result.duration_s,
                peak=result.peak,
                rms=result.rms,
                dominant_hz=result.dominant_hz,
                centroid_hz=result.centroid_hz,
                zcr=result.zcr,
                ratio=result.ratio,
                band_energy=feat.get("band_energy", 0.0),
                core_s=feat.get("core_s", 0.0),
            )
        )
        level = CLASS_LEVEL.get(cls, 1)
        if result.duration_s < self.settings.detection.min_duration_s:
            return None
        kind = _LEVEL_TO_KIND.get(level, EventKind.NOISE)
        return DetectionEvent(
            sensor_id=sensor_id,
            zone_id=zone_id,
            kind=kind,
            level=EventLevel(level),
            event_class=cls,
            confidence=confidence,
            ratio=result.ratio,
            peak=result.peak,
            duration_s=result.duration_s,
            dominant_hz=result.dominant_hz,
            meta={"rms": result.rms, "centroid_hz": result.centroid_hz, "zcr": result.zcr},
        )

    async def handle_event(self, event: DetectionEvent) -> None:
        """Сохранить событие, при необходимости сформировать тревогу."""
        await self.store.add_event(event)
        self._events_total += 1
        self.bus.publish("event", event.to_public())

        zone = self.registry.zones.get(event.zone_id)
        zone_armed = zone.armed if zone else True
        if (
            event.level >= EventLevel.ALARM
            and zone_armed
            and self._state in (SystemState.ARMED, SystemState.ALARM)
        ):
            alarm = Alarm(
                sensor_id=event.sensor_id,
                zone_id=event.zone_id,
                level=event.level,
                event_class=event.event_class,
                confidence=event.confidence,
                event_ids=[event.id],
            )
            self._alarms[alarm.id] = alarm
            await self.store.add_alarm(alarm)
            self._state = SystemState.ALARM
            self.bus.publish("alarm", alarm.to_public())

    async def process_samples(self, samples: list[ChainSample]) -> list[DetectionEvent]:
        """Обработать пачку блоков от цепочки датчиков."""
        produced: list[DetectionEvent] = []
        for sample in samples:
            for event in self.ingest(sample):
                produced.append(event)
                await self.handle_event(event)
        return produced

    # -- фоновые задачи -------------------------------------------------
    async def run_chain(self, chain: ChainReader) -> None:
        """Фоновый цикл обработки одной цепочки датчиков."""
        async for samples in chain.astream():
            if not self._running:
                break
            try:
                await self.process_samples(samples)
            except Exception:  # noqa: BLE001 - не роняем цикл сбора
                await asyncio.sleep(0.05)

    def start(self, chains: list[ChainReader]) -> None:
        self._running = True
        for chain in chains:
            task = asyncio.create_task(self.run_chain(chain))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def stop(self) -> None:
        self._running = False
        for task in list(self._tasks):
            task.cancel()
        for task in list(self._tasks):
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._tasks.clear()

    # -- тревоги --------------------------------------------------------
    def active_alarms(self) -> list[Alarm]:
        return [a for a in self._alarms.values() if a.state == AlarmState.ACTIVE]

    async def acknowledge(self, alarm_id: str, user: str = "operator", comment: str = "") -> Alarm | None:
        alarm = self._alarms.get(alarm_id)
        if alarm is None:
            return None
        alarm.state = AlarmState.ACKNOWLEDGED
        alarm.ack_ts = time.time()
        alarm.ack_by = user
        alarm.comment = comment
        await self.store.add_alarm(alarm)
        await self.store.audit(user, "ack_alarm", alarm_id)
        self.bus.publish("alarm_update", alarm.to_public())
        if not self.active_alarms():
            self._state = SystemState.ARMED
        return alarm

    async def reset_alarm(self, alarm_id: str, user: str = "operator") -> Alarm | None:
        alarm = self._alarms.get(alarm_id)
        if alarm is None:
            return None
        alarm.state = AlarmState.RESET
        await self.store.add_alarm(alarm)
        await self.store.audit(user, "reset_alarm", alarm_id)
        self.bus.publish("alarm_update", alarm.to_public())
        return alarm

    # -- статус ---------------------------------------------------------
    async def status(self) -> SystemStatus:
        summary = self.registry.summary()
        return SystemStatus(
            state=self._state,
            sensors_total=summary["sensors_total"],
            sensors_online=summary["sensors_online"],
            zones_total=summary["zones_total"],
            zones_armed=summary["zones_armed"],
            active_alarms=len(self.active_alarms()),
            events_total=self._events_total,
            uptime_s=time.time() - self._started_at,
            version="1.0.0",
            started_at=self._started_at,
        )
