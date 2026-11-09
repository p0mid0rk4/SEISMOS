"""Доменные модели SEISMOS: датчики, зоны, события, тревоги."""

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class EventKind(str, Enum):
    """Тип зафиксированного события."""

    NOISE = "noise"
    WARNING = "warning"
    ALARM = "alarm"
    INTRUSION = "intrusion"
    TAMPER = "tamper"
    SENSOR_ONLINE = "sensor_online"
    SENSOR_OFFLINE = "sensor_offline"
    SYSTEM = "system"


class EventLevel(int, Enum):
    """Уровень значимости события. Больше — важнее."""

    INFO = 0
    WARNING = 1
    ALARM = 2
    INTRUSION = 3


class EventClass(str, Enum):
    """Класс физического воздействия, определённый классификатором."""

    NONE = "none"
    FOOTSTEP = "footstep"        # шаги человека
    GROUP = "group"              # группа людей
    VEHICLE = "vehicle"          # техника
    DIGGING = "digging"          # подкоп / земляные работы
    CLIMB = "climb"              # перелаз через ограждение
    IMPACT = "impact"            # удар по ограждению
    TAMPER = "tamper"            # попытка снятия/закрытия датчика
    WEATHER = "weather"          # метео (дождь, ветер, град)
    UNKNOWN = "unknown"


class SystemState(str, Enum):
    """Режим работы системы."""

    DISARMED = "disarmed"
    ARMING = "arming"
    ARMED = "armed"
    ALARM = "alarm"


class AlarmState(str, Enum):
    """Жизненный цикл тревоги."""

    ACTIVE = "active"
    ACKNOWLEDGED = "acknowledged"
    RESET = "reset"


class SensorKind(str, Enum):
    """Тип чувствительного элемента."""

    GS20DX = "gs20dx"            # сейсмический геофон GS-20DX
    GS20DX_ARRAY = "gs20dx-array"  # группа геофонов
    VIBRO = "vibro"              # вибрационный (совместимость с рубежами)
    CONTACT = "contact"          # магнитоконтактный (калитки/ворота)


class Sensor(BaseModel):
    """Сейсмический датчик на периметре."""

    id: str
    name: str
    zone_id: str
    kind: SensorKind = SensorKind.GS20DX
    chain_index: int = Field(0, description="Позиция в последовательной цепочке")
    address: str | None = Field(None, description="IP-адрес узла (Ethernet/PoE)")
    channel: int = 0
    sample_rate: int = 1000
    sensitivity_v_per_m_s: float = 28.8
    gain_db: float = 0.0
    enabled: bool = True
    position_m: float = Field(0.0, description="Погонная координата на периметре, м")
    x: float | None = None
    y: float | None = None
    online: bool = False
    last_seen: float | None = None

    def to_public(self) -> dict[str, Any]:
        data = self.model_dump()
        data.pop("address", None)
        return data


class Zone(BaseModel):
    """Зона охраны — участок периметра."""

    id: str
    name: str
    kind: str = "seismic"          # seismic | vibro | combined | gate
    priority: int = 1
    length_m: float = 0.0
    sensor_ids: list[str] = Field(default_factory=list)
    armed: bool = True
    description: str = ""


class DetectionEvent(BaseModel):
    """Событие обнаружения, сформированное движком детекции."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:16])
    ts: float = Field(default_factory=time.time)
    sensor_id: str
    zone_id: str
    kind: EventKind = EventKind.NOISE
    level: EventLevel = EventLevel.INFO
    event_class: EventClass = EventClass.NONE
    confidence: float = 0.0
    ratio: float = Field(0.0, description="Отношение STA/LTA в момент срабатывания")
    peak: float = Field(0.0, description="Пиковая амплитуда, мкм/с")
    duration_s: float = 0.0
    dominant_hz: float = 0.0
    meta: dict[str, Any] = Field(default_factory=dict)

    def to_public(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class Alarm(BaseModel):
    """Тревога — агрегированное событие, требующее реакции оператора."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:16])
    ts: float = Field(default_factory=time.time)
    sensor_id: str
    zone_id: str
    level: EventLevel = EventLevel.ALARM
    event_class: EventClass = EventClass.UNKNOWN
    confidence: float = 0.0
    state: AlarmState = AlarmState.ACTIVE
    ack_ts: float | None = None
    ack_by: str | None = None
    comment: str = ""
    event_ids: list[str] = Field(default_factory=list)

    def to_public(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class SystemStatus(BaseModel):
    """Текущее состояние системы."""

    state: SystemState = SystemState.DISARMED
    sensors_total: int = 0
    sensors_online: int = 0
    zones_total: int = 0
    zones_armed: int = 0
    active_alarms: int = 0
    events_total: int = 0
    uptime_s: float = 0.0
    version: str = ""
    started_at: float = Field(default_factory=time.time)
