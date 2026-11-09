"""Реестр объектов: датчики, цепочки, зоны охраны."""

from __future__ import annotations

from .config import SiteConfig
from .models import Sensor, Zone


class Registry:
    """Реестр оборудования и зон, построенный из конфигурации объекта."""

    def __init__(self, site: SiteConfig) -> None:
        self.site = site
        self.sensors: dict[str, Sensor] = {}
        self.zones: dict[str, Zone] = {}
        self.chains: dict[str, list[Sensor]] = {}
        self._build()

    def _build(self) -> None:
        for sensor in self.site.parsed_sensors():
            self.sensors[sensor.id] = sensor
        for zone in self.site.parsed_zones():
            self.zones[zone.id] = zone
        for chain in self.site.chains:
            members = [self.sensors[s] for s in chain.sensors if s in self.sensors]
            members.sort(key=lambda s: s.chain_index)
            self.chains[chain.id] = members

    # -- датчики --------------------------------------------------------
    def sensor(self, sensor_id: str) -> Sensor | None:
        return self.sensors.get(sensor_id)

    def zone_of(self, sensor_id: str) -> Zone | None:
        sensor = self.sensors.get(sensor_id)
        if sensor is None:
            return None
        return self.zones.get(sensor.zone_id)

    def sensors_in_zone(self, zone_id: str) -> list[Sensor]:
        return sorted(
            (s for s in self.sensors.values() if s.zone_id == zone_id),
            key=lambda s: s.chain_index,
        )

    def zone_sensor_ids(self, zone_id: str) -> list[str]:
        zone = self.zones.get(zone_id)
        if zone and zone.sensor_ids:
            return list(zone.sensor_ids)
        return [s.id for s in self.sensors_in_zone(zone_id)]

    def neighbor_sensors(self, sensor_id: str) -> list[Sensor]:
        """Соседние датчики по цепочке (предыдущий и следующий)."""
        chain = next((c for c in self.chains.values() if any(
            s.id == sensor_id for s in c)), None)
        if not chain:
            return []
        idx = next((i for i, s in enumerate(chain) if s.id == sensor_id), None)
        if idx is None:
            return []
        out: list[Sensor] = []
        if idx > 0:
            out.append(chain[idx - 1])
        if idx + 1 < len(chain):
            out.append(chain[idx + 1])
        return out

    def mark_online(self, sensor_id: str, online: bool) -> Sensor | None:
        sensor = self.sensors.get(sensor_id)
        if sensor is None:
            return None
        sensor.online = online
        return sensor

    # -- сводки ---------------------------------------------------------
    def summary(self) -> dict[str, int]:
        return {
            "sensors_total": len(self.sensors),
            "sensors_online": sum(1 for s in self.sensors.values() if s.online),
            "zones_total": len(self.zones),
            "zones_armed": sum(1 for z in self.zones.values() if z.armed),
        }

    def zones_containing(self, sensor_id: str) -> list[Zone]:
        out: list[Zone] = []
        for zone in self.zones.values():
            if sensor_id in self.zone_sensor_ids(zone.id):
                out.append(zone)
        return out
