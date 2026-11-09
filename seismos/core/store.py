"""Хранилище данных SEISMOS: журнал событий и тревог (SQLite)."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from collections import deque
from pathlib import Path
from typing import Any

from .models import Alarm, AlarmState, DetectionEvent, EventLevel

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id          TEXT PRIMARY KEY,
    ts          REAL NOT NULL,
    sensor_id   TEXT NOT NULL,
    zone_id     TEXT NOT NULL,
    kind        TEXT NOT NULL,
    level       INTEGER NOT NULL,
    event_class TEXT NOT NULL,
    confidence  REAL NOT NULL,
    ratio       REAL NOT NULL,
    peak        REAL NOT NULL,
    duration_s  REAL NOT NULL,
    dominant_hz REAL NOT NULL,
    meta        TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_zone ON events(zone_id, ts);

CREATE TABLE IF NOT EXISTS alarms (
    id          TEXT PRIMARY KEY,
    ts          REAL NOT NULL,
    sensor_id   TEXT NOT NULL,
    zone_id     TEXT NOT NULL,
    level       INTEGER NOT NULL,
    event_class TEXT NOT NULL,
    confidence  REAL NOT NULL,
    state       TEXT NOT NULL,
    ack_ts      REAL,
    ack_by      TEXT,
    comment     TEXT NOT NULL DEFAULT '',
    event_ids   TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_alarms_ts ON alarms(ts);
CREATE INDEX IF NOT EXISTS idx_alarms_state ON alarms(state);

CREATE TABLE IF NOT EXISTS audit (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    ts   REAL NOT NULL,
    user TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT ''
);
"""


class EventStore:
    """Асинхронное хранилище журнала событий и тревог.

    Записи выполняются в отдельном потоке через ``asyncio.to_thread``,
    чтобы не блокировать событийный цикл API. Дополнительно ведётся
    оперативный кольцевой буфер последних событий для быстрой выдачи
    в WebSocket-поток.
    """

    def __init__(self, db_path: str | Path, ring_size: int = 2000) -> None:
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._ring: deque[DetectionEvent] = deque(maxlen=ring_size)
        self._lock = asyncio.Lock()
        self._conn: sqlite3.Connection | None = None

    # -- низкоуровневое соединение -------------------------------------
    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.executescript(SCHEMA)
            self._conn.commit()
        return self._conn

    def _sync_init(self) -> None:
        self._connect()

    async def init(self) -> None:
        await asyncio.to_thread(self._sync_init)

    async def close(self) -> None:
        if self._conn is not None:
            await asyncio.to_thread(self._conn.close)
            self._conn = None

    # -- запись ---------------------------------------------------------
    def _sync_add_event(self, ev: DetectionEvent) -> None:
        conn = self._connect()
        conn.execute(
            "INSERT OR REPLACE INTO events (id, ts, sensor_id, zone_id, kind, level,"
            " event_class, confidence, ratio, peak, duration_s, dominant_hz, meta)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                ev.id, ev.ts, ev.sensor_id, ev.zone_id, ev.kind.value, int(ev.level),
                ev.event_class.value, ev.confidence, ev.ratio, ev.peak,
                ev.duration_s, ev.dominant_hz, json.dumps(ev.meta, ensure_ascii=False),
            ),
        )
        conn.commit()

    async def add_event(self, ev: DetectionEvent) -> None:
        async with self._lock:
            self._ring.append(ev)
            await asyncio.to_thread(self._sync_add_event, ev)

    def recent(self, limit: int = 100) -> list[DetectionEvent]:
        items = list(self._ring)[-limit:]
        items.reverse()
        return items

    # -- выборка --------------------------------------------------------
    def _sync_query_events(
        self, zone_id: str | None, since: float | None, until: float | None,
        min_level: int, limit: int, offset: int,
    ) -> list[dict[str, Any]]:
        conn = self._connect()
        sql = "SELECT * FROM events WHERE level >= ?"
        args: list[Any] = [min_level]
        if zone_id:
            sql += " AND zone_id = ?"
            args.append(zone_id)
        if since is not None:
            sql += " AND ts >= ?"
            args.append(since)
        if until is not None:
            sql += " AND ts <= ?"
            args.append(until)
        sql += " ORDER BY ts DESC LIMIT ? OFFSET ?"
        args.extend([limit, offset])
        rows = conn.execute(sql, args).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["meta"] = json.loads(d.get("meta") or "{}")
            out.append(d)
        return out

    async def query_events(
        self, zone_id: str | None = None, since: float | None = None,
        until: float | None = None, min_level: int = 0, limit: int = 200,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(
            self._sync_query_events, zone_id, since, until, min_level, limit, offset
        )

    # -- тревоги --------------------------------------------------------
    def _sync_add_alarm(self, al: Alarm) -> None:
        conn = self._connect()
        conn.execute(
            "INSERT OR REPLACE INTO alarms (id, ts, sensor_id, zone_id, level,"
            " event_class, confidence, state, ack_ts, ack_by, comment, event_ids)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                al.id, al.ts, al.sensor_id, al.zone_id, int(al.level),
                al.event_class.value, al.confidence, al.state.value, al.ack_ts,
                al.ack_by, al.comment, json.dumps(al.event_ids),
            ),
        )
        conn.commit()

    async def add_alarm(self, al: Alarm) -> None:
        await asyncio.to_thread(self._sync_add_alarm, al)

    def _sync_query_alarms(
        self, state: str | None, zone_id: str | None, limit: int
    ) -> list[dict[str, Any]]:
        conn = self._connect()
        sql = "SELECT * FROM alarms WHERE 1=1"
        args: list[Any] = []
        if state:
            sql += " AND state = ?"
            args.append(state)
        if zone_id:
            sql += " AND zone_id = ?"
            args.append(zone_id)
        sql += " ORDER BY ts DESC LIMIT ?"
        args.append(limit)
        rows = conn.execute(sql, args).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["event_ids"] = json.loads(d.get("event_ids") or "[]")
            out.append(d)
        return out

    async def query_alarms(
        self, state: str | None = None, zone_id: str | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._sync_query_alarms, state, zone_id, limit)

    def _sync_count_alarms(self, state: str) -> int:
        conn = self._connect()
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM alarms WHERE state = ?", (state,)
        ).fetchone()
        return int(row["c"])

    async def count_alarms(self, state: AlarmState = AlarmState.ACTIVE) -> int:
        return await asyncio.to_thread(self._sync_count_alarms, state.value)

    # -- аудит ----------------------------------------------------------
    def _sync_audit(self, user: str, action: str, detail: str) -> None:
        conn = self._connect()
        conn.execute(
            "INSERT INTO audit (ts, user, action, detail) VALUES (?,?,?,?)",
            (time.time(), user, action, detail),
        )
        conn.commit()

    async def audit(self, user: str, action: str, detail: str = "") -> None:
        await asyncio.to_thread(self._sync_audit, user, action, detail)

    # -- обслуживание ---------------------------------------------------
    def _sync_purge(self, before_ts: float) -> int:
        conn = self._connect()
        cur = conn.execute("DELETE FROM events WHERE ts < ?", (before_ts,))
        conn.commit()
        return cur.rowcount

    async def purge_older_than(self, days: int) -> int:
        cutoff = time.time() - days * 86400
        return await asyncio.to_thread(self._sync_purge, cutoff)

    def _sync_stats(self) -> dict[str, Any]:
        conn = self._connect()
        total = conn.execute("SELECT COUNT(*) AS c FROM events").fetchone()["c"]
        by_class = conn.execute(
            "SELECT event_class, COUNT(*) AS c FROM events GROUP BY event_class"
        ).fetchall()
        by_zone = conn.execute(
            "SELECT zone_id, COUNT(*) AS c FROM events"
            " WHERE level >= ? GROUP BY zone_id ORDER BY c DESC",
            (int(EventLevel.ALARM),),
        ).fetchall()
        return {
            "events_total": int(total),
            "by_class": {r["event_class"]: int(r["c"]) for r in by_class},
            "alarms_by_zone": {r["zone_id"]: int(r["c"]) for r in by_zone},
        }

    async def stats(self) -> dict[str, Any]:
        return await asyncio.to_thread(self._sync_stats)
