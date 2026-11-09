"""REST и WebSocket API системы SEISMOS."""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
from fastapi import (
    Body,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..core.bus import EventBus
from ..core.config import Settings, SiteConfig, ensure_dirs, get_settings
from ..core.engine import ProcessingEngine
from ..core.models import EventClass
from ..core.registry import Registry
from ..core.store import EventStore
from .context import AppContext, get_context, set_context

CONSOLE_DIR = Path(__file__).resolve().parent.parent.parent / "console"


def _db_path(settings: Settings) -> str:
    url = settings.database_url
    if url.startswith("sqlite:///"):
        return url[len("sqlite:///"):]
    if url == "sqlite://:memory:":
        return ":memory:"
    return "data/seismos.db"


async def auth_dependency(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
) -> str:
    """Простая проверка токена доступа (если он задан в настройках)."""
    ctx = get_context()
    token = ctx.settings.auth_token
    if not token:
        return "anonymous"
    provided = None
    if authorization and authorization.lower().startswith("bearer "):
        provided = authorization[7:]
    elif x_api_key:
        provided = x_api_key
    if provided != token:
        raise HTTPException(status_code=401, detail="Неверный токен доступа")
    return "operator"


def create_app(settings: Settings | None = None, site: SiteConfig | None = None,
               simulate: bool = False) -> FastAPI:
    settings = settings or get_settings()
    ensure_dirs(settings)
    site = site or settings.load_site()
    registry = Registry(site)
    store = EventStore(_db_path(settings))
    bus = EventBus()
    engine = ProcessingEngine(settings, registry, store, bus)

    ctx = AppContext(
        settings=settings, site=site, registry=registry, store=store,
        bus=bus, engine=engine, simulate=simulate,
    )
    set_context(ctx)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await store.init()
        try:
            yield
        finally:
            await engine.stop()
            await store.close()

    app = FastAPI(
        title="SEISMOS API",
        description="Система контроля периметра на геофонах GS-20DX",
        version=__version__,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # -- системные ------------------------------------------------------
    @app.get("/health", tags=["system"])
    async def health() -> dict[str, object]:
        return {"status": "ok", "version": __version__, "ts": time.time()}

    @app.get("/api/v1/status", tags=["system"])
    async def status() -> dict[str, object]:
        return (await engine.status()).model_dump(mode="json")

    @app.get("/api/v1/metrics", tags=["system"])
    async def metrics() -> dict[str, object]:
        stats = await store.stats()
        summary = registry.summary()
        return {
            "sensors": summary,
            "events": stats,
            "active_alarms": len(engine.active_alarms()),
            "subscribers": bus.subscriber_count,
            "state": engine.state.value,
        }

    # -- датчики и зоны -------------------------------------------------
    @app.get("/api/v1/sensors", tags=["perimeter"])
    async def list_sensors() -> list[dict[str, object]]:
        return [s.to_public() for s in registry.sensors.values()]

    @app.get("/api/v1/sensors/{sensor_id}", tags=["perimeter"])
    async def get_sensor(sensor_id: str) -> dict[str, object]:
        sensor = registry.sensor(sensor_id)
        if sensor is None:
            raise HTTPException(404, "Датчик не найден")
        return sensor.to_public()

    @app.get("/api/v1/zones", tags=["perimeter"])
    async def list_zones() -> list[dict[str, object]]:
        out = []
        for zone in registry.zones.values():
            data = zone.model_dump()
            data["sensor_count"] = len(registry.sensors_in_zone(zone.id))
            data["active_alarms"] = sum(
                1 for a in engine.active_alarms() if a.zone_id == zone.id
            )
            out.append(data)
        return out

    @app.get("/api/v1/zones/{zone_id}", tags=["perimeter"])
    async def get_zone(zone_id: str) -> dict[str, object]:
        zone = registry.zones.get(zone_id)
        if zone is None:
            raise HTTPException(404, "Зона не найдена")
        return zone.model_dump()

    # -- режим охраны ---------------------------------------------------
    @app.post("/api/v1/arm", tags=["control"])
    async def arm(user: str = Depends(auth_dependency)) -> dict[str, str]:
        await engine.arm(user)
        return {"state": engine.state.value}

    @app.post("/api/v1/disarm", tags=["control"])
    async def disarm(user: str = Depends(auth_dependency)) -> dict[str, str]:
        await engine.disarm(user)
        return {"state": engine.state.value}

    @app.post("/api/v1/zones/{zone_id}/arm", tags=["control"])
    async def arm_zone(zone_id: str, armed: bool = Body(True, embed=True),
                       user: str = Depends(auth_dependency)) -> dict[str, object]:
        zone = registry.zones.get(zone_id)
        if zone is None:
            raise HTTPException(404, "Зона не найдена")
        zone.armed = armed
        await store.audit(user, "zone_arm", f"{zone_id}={armed}")
        bus.publish("zone", {"zone_id": zone_id, "armed": armed})
        return {"zone_id": zone_id, "armed": armed}

    # -- события --------------------------------------------------------
    @app.get("/api/v1/events", tags=["events"])
    async def list_events(
        zone_id: str | None = None,
        since: float | None = None,
        until: float | None = None,
        min_level: int = Query(0, ge=0, le=3),
        limit: int = Query(200, ge=1, le=5000),
        offset: int = Query(0, ge=0),
    ) -> list[dict[str, object]]:
        return await store.query_events(zone_id, since, until, min_level, limit, offset)

    @app.get("/api/v1/events/recent", tags=["events"])
    async def recent_events(limit: int = Query(50, ge=1, le=500)) -> list[dict[str, object]]:
        return [e.to_public() for e in store.recent(limit)]

    # -- тревоги --------------------------------------------------------
    @app.get("/api/v1/alarms", tags=["alarms"])
    async def list_alarms(
        state: str | None = None,
        zone_id: str | None = None,
        limit: int = Query(200, ge=1, le=5000),
    ) -> list[dict[str, object]]:
        return await store.query_alarms(state, zone_id, limit)

    @app.get("/api/v1/alarms/active", tags=["alarms"])
    async def active_alarms() -> list[dict[str, object]]:
        return [a.to_public() for a in engine.active_alarms()]

    @app.post("/api/v1/alarms/{alarm_id}/ack", tags=["alarms"])
    async def ack_alarm(alarm_id: str, comment: str = Body("", embed=True),
                        user: str = Depends(auth_dependency)) -> dict[str, object]:
        alarm = await engine.acknowledge(alarm_id, user, comment)
        if alarm is None:
            raise HTTPException(404, "Тревога не найдена")
        return alarm.to_public()

    @app.post("/api/v1/alarms/{alarm_id}/reset", tags=["alarms"])
    async def reset_alarm(alarm_id: str, user: str = Depends(auth_dependency)) -> dict[str, object]:
        alarm = await engine.reset_alarm(alarm_id, user)
        if alarm is None:
            raise HTTPException(404, "Тревога не найдена")
        return alarm.to_public()

    # -- демонстрация / стенд -------------------------------------------
    @app.post("/api/v1/simulate", tags=["system"])
    async def simulate_event(
        sensor_id: str = Body(..., embed=True),
        event_class: EventClass = Body(EventClass.FOOTSTEP, embed=True),
        duration_s: float = Body(2.0, embed=True),
        user: str = Depends(auth_dependency),
    ) -> dict[str, object]:
        """Вбросить синтетическое воздействие (стенд/демонстрация)."""
        from ..hardware.simulator import SeismicSignalGenerator

        sensor = registry.sensor(sensor_id)
        if sensor is None:
            raise HTTPException(404, "Датчик не найден")
        gen = SeismicSignalGenerator(sample_rate=settings.detection.sample_rate)
        # Базовый шум до воздействия: детектору нужен период набора
        # оценки фона (LTA/CFAR), иначе срабатывание невозможно.
        baseline_s = max(1.5, 2.0 * settings.detection.lta_len / settings.detection.sample_rate)
        signal = np.concatenate([
            gen.background(baseline_s),
            gen.by_class(event_class, duration_s),
            gen.background(1.5),
        ])
        from ..hardware.chain import ChainSample

        produced = []
        chunk = 128
        for start in range(0, signal.size, chunk):
            block = signal[start:start + chunk]
            sample = ChainSample(sensor_id, block, time.time(), 0)
            produced.extend(engine.ingest(sample))
        for event in produced:
            await engine.handle_event(event)
        await store.audit(user, "simulate", f"{sensor_id}:{event_class.value}")
        return {"injected": signal.size, "events": [e.to_public() for e in produced]}

    # -- WebSocket ------------------------------------------------------
    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket) -> None:
        await ws.accept()
        queue = await bus.subscribe()
        try:
            await ws.send_json({"topic": "hello", "payload": {
                "version": __version__, "state": engine.state.value}})
            while True:
                message = await queue.get()
                await ws.send_json(message)
        except WebSocketDisconnect:
            pass
        except Exception:  # noqa: BLE001
            pass
        finally:
            await bus.unsubscribe(queue)

    # -- консоль оператора ---------------------------------------------
    if CONSOLE_DIR.exists():
        app.mount("/console", StaticFiles(directory=str(CONSOLE_DIR), html=True), name="console")

        @app.get("/", include_in_schema=False)
        async def index() -> FileResponse:
            return FileResponse(str(CONSOLE_DIR / "index.html"))

    @app.exception_handler(Exception)
    async def unhandled(_, exc: Exception) -> JSONResponse:  # pragma: no cover
        return JSONResponse(status_code=500, content={"detail": str(exc)})

    return app
