"""Прикладное состояние (контекст) API SEISMOS."""

from __future__ import annotations

from dataclasses import dataclass

from ..core.bus import EventBus
from ..core.config import Settings, SiteConfig
from ..core.engine import ProcessingEngine
from ..core.registry import Registry
from ..core.store import EventStore


@dataclass
class AppContext:
    """Общие объекты, доступные обработчикам API."""

    settings: Settings
    site: SiteConfig
    registry: Registry
    store: EventStore
    bus: EventBus
    engine: ProcessingEngine
    simulate: bool = False


_context: AppContext | None = None


def set_context(ctx: AppContext) -> None:
    global _context
    _context = ctx


def get_context() -> AppContext:
    if _context is None:  # pragma: no cover - защитная ветка
        raise RuntimeError("Контекст приложения не инициализирован")
    return _context
