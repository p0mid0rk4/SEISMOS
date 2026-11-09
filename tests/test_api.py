"""Тесты API SEISMOS (REST + WebSocket)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from seismos.api.app import create_app
from seismos.core.config import Settings, SiteConfig


@pytest.fixture
def client() -> TestClient:
    settings = Settings(database_url="sqlite://:memory:", site_config="nonexistent.yaml")
    site = SiteConfig(
        name="Тест",
        perimeter_length_m=400,
        sensors=[
            {"id": "S01", "name": "Д1", "zone_id": "Z1", "chain_index": 0, "position_m": 0},
            {"id": "S02", "name": "Д2", "zone_id": "Z1", "chain_index": 1, "position_m": 200},
        ],
        zones=[{"id": "Z1", "name": "Север", "kind": "seismic", "length_m": 200}],
        chains=[{"id": "CH1", "transport": "sim", "sensors": ["S01", "S02"]}],
    )
    app = create_app(settings, site, simulate=True)
    with TestClient(app) as c:
        yield c


def test_health(client: TestClient):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_status_endpoint(client: TestClient):
    r = client.get("/api/v1/status")
    assert r.status_code == 200
    body = r.json()
    assert body["sensors_total"] == 2
    assert body["state"] == "disarmed"


def test_list_sensors_and_zones(client: TestClient):
    sensors = client.get("/api/v1/sensors").json()
    assert {s["id"] for s in sensors} == {"S01", "S02"}
    zones = client.get("/api/v1/zones").json()
    assert zones[0]["id"] == "Z1"
    assert zones[0]["sensor_count"] == 2


def test_arm_and_disarm(client: TestClient):
    assert client.post("/api/v1/arm").json()["state"] == "armed"
    assert client.get("/api/v1/status").json()["state"] == "armed"
    assert client.post("/api/v1/disarm").json()["state"] == "disarmed"


def test_zone_arm_toggle(client: TestClient):
    r = client.post("/api/v1/zones/Z1/arm", json={"armed": False})
    assert r.status_code == 200
    assert r.json()["armed"] is False
    zone = client.get("/api/v1/zones/Z1").json()
    assert zone["armed"] is False


def test_simulate_triggers_detection(client: TestClient):
    client.post("/api/v1/arm")
    r = client.post("/api/v1/simulate", json={
        "sensor_id": "S01", "event_class": "vehicle", "duration_s": 4.0,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["injected"] > 0
    assert len(body["events"]) >= 1

    events = client.get("/api/v1/events").json()
    assert len(events) >= 1
    assert events[0]["sensor_id"] == "S01"


def test_alarm_acknowledge_flow(client: TestClient):
    client.post("/api/v1/arm")
    client.post("/api/v1/simulate", json={
        "sensor_id": "S01", "event_class": "digging", "duration_s": 4.0,
    })
    alarms = client.get("/api/v1/alarms/active").json()
    assert alarms, "Ожидалась активная тревога"
    alarm_id = alarms[0]["id"]
    acked = client.post(f"/api/v1/alarms/{alarm_id}/ack", json={"comment": "ок"})
    assert acked.status_code == 200
    assert acked.json()["state"] == "acknowledged"
    assert client.get("/api/v1/alarms/active").json() == []


def test_metrics_endpoint(client: TestClient):
    r = client.get("/api/v1/metrics")
    assert r.status_code == 200
    assert "sensors" in r.json()
    assert "events" in r.json()


def test_unknown_sensor_returns_404(client: TestClient):
    assert client.get("/api/v1/sensors/NOPE").status_code == 404


def test_websocket_stream(client: TestClient):
    client.post("/api/v1/arm")
    with client.websocket_connect("/ws") as ws:
        hello = ws.receive_json()
        assert hello["topic"] == "hello"
        client.post("/api/v1/simulate", json={
            "sensor_id": "S01", "event_class": "footstep", "duration_s": 3.0,
        })
        seen = set()
        for _ in range(6):
            msg = ws.receive_json()
            seen.add(msg["topic"])
            if "event" in seen:
                break
        assert "event" in seen
