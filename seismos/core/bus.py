"""Шина событий SEISMOS для рассылки подписчикам (WebSocket, интеграции)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any


class EventBus:
    """Простая широковещательная шина с неблокирующей доставкой.

    Каждому подписчику соответствует очередь ограниченного размера. При
    переполнении самое старое сообщение отбрасывается, чтобы медленный
    подписчик не тормозил обработку сигнала.
    """

    def __init__(self, maxsize: int = 512) -> None:
        self._maxsize = maxsize
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._lock = asyncio.Lock()

    async def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self._maxsize)
        async with self._lock:
            self._subscribers.add(q)
        return q

    async def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        async with self._lock:
            self._subscribers.discard(q)

    def publish(self, topic: str, payload: dict[str, Any]) -> None:
        message = {"topic": topic, "payload": payload}
        for q in list(self._subscribers):
            if q.full():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:  # pragma: no cover - гонка
                    pass
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:  # pragma: no cover - гонка
                pass

    async def stream(self) -> AsyncIterator[dict[str, Any]]:
        q = await self.subscribe()
        try:
            while True:
                yield await q.get()
        finally:
            await self.unsubscribe(q)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)
