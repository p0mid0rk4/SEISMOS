"""Командная строка SEISMOS.

Команды:
    seismos serve        — запуск API и консоли оператора;
    seismos simulate     — стенд: генерация сигналов и прогон детекции;
    seismos selftest     — самопроверка конвейера обработки;
    seismos sensors      — вывод конфигурации датчиков и зон;
    seismos version      — версия системы.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

import numpy as np

from .. import __version__
from ..core.bus import EventBus
from ..core.config import ensure_dirs, get_settings
from ..core.engine import ProcessingEngine
from ..core.models import EventClass, SystemState
from ..core.registry import Registry
from ..core.store import EventStore


def _build_engine(simulate: bool = False):
    settings = get_settings()
    ensure_dirs(settings)
    site = settings.load_site()
    registry = Registry(site)
    db_path = settings.database_url.replace("sqlite:///", "")
    store = EventStore(db_path)
    bus = EventBus()
    engine = ProcessingEngine(settings, registry, store, bus)
    return settings, site, registry, store, bus, engine


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from ..api.app import create_app

    settings = get_settings()
    if args.host:
        settings.host = args.host
    if args.port:
        settings.port = args.port
    app = create_app(settings)
    uvicorn.run(app, host=settings.host, port=settings.port, log_level=settings.log_level.lower())
    return 0


def cmd_simulate(args: argparse.Namespace) -> int:
    from ..core.models import EventClass
    from ..hardware.chain import ChainSample
    from ..hardware.simulator import SeismicSignalGenerator

    settings, _, registry, store, _, engine = _build_engine(simulate=True)

    async def run() -> int:
        await store.init()
        await engine.set_state(SystemState.ARMED)
        gen = SeismicSignalGenerator(sample_rate=settings.detection.sample_rate, seed=args.seed)
        event_map = {
            "footstep": EventClass.FOOTSTEP,
            "group": EventClass.GROUP,
            "vehicle": EventClass.VEHICLE,
            "digging": EventClass.DIGGING,
            "climb": EventClass.CLIMB,
            "impact": EventClass.IMPACT,
            "weather": EventClass.WEATHER,
        }
        event_class = event_map.get(args.event, EventClass.FOOTSTEP)
        baseline = gen.background(max(1.5, 2.0 * settings.detection.lta_len / settings.detection.sample_rate))
        signal = np.concatenate([baseline, gen.by_class(event_class, args.duration), gen.background(1.5)])
        target = args.sensor or next(iter(registry.sensors), None)
        if target is None:
            print("Нет датчиков в конфигурации", file=sys.stderr)
            return 2
        produced = []
        for start in range(0, signal.size, 128):
            sample = ChainSample(target, signal[start:start + 128], 0.0, 0)
            for event in engine.ingest(sample):
                produced.append(event)
                await engine.handle_event(event)
        for event in produced:
            print(json.dumps(event.to_public(), ensure_ascii=False))
        print(f"Событий обнаружено: {len(produced)}")
        await store.close()
        return 0

    return asyncio.run(run())


def cmd_selftest(args: argparse.Namespace) -> int:
    from ..hardware.chain import ChainSample
    from ..hardware.simulator import SeismicSignalGenerator

    settings = get_settings()
    ensure_dirs(settings)
    site = settings.load_site()
    registry = Registry(site)

    def detect(event_class, duration_s: float, seed: int):
        """Прогнать воздействие через чистый конвейер, вернуть события."""
        # Отдельный движок на каждый случай: детектор не должен наследовать
        # состояние (STA/LTA, CFAR) от предыдущего воздействия.
        store = EventStore(":memory:")
        engine = ProcessingEngine(settings, registry, store, EventBus())
        gen = SeismicSignalGenerator(sample_rate=settings.detection.sample_rate, seed=seed)
        baseline_s = max(1.5, 2.0 * settings.detection.lta_len / settings.detection.sample_rate)
        signal = np.concatenate([
            gen.background(baseline_s),
            gen.by_class(event_class, duration_s),
            gen.background(1.5),
        ])
        target = next(iter(registry.sensors), None)
        events = []
        for start in range(0, signal.size, 128):
            sample = ChainSample(target, signal[start:start + 128], 0.0, 0)
            events.extend(engine.ingest(sample))
        return events

    if not registry.sensors:
        print("FAIL: нет датчиков в конфигурации")
        return 2

    # (класс, ожидается событие этого класса, ожидается тревога)
    cases = [
        (EventClass.FOOTSTEP, True, False),
        (EventClass.GROUP, True, True),
        (EventClass.VEHICLE, True, True),
        (EventClass.DIGGING, True, True),
        (EventClass.IMPACT, True, True),
        (EventClass.WEATHER, False, False),
    ]
    ok = True
    for idx, (cls, expect_event, expect_alarm) in enumerate(cases):
        events = detect(cls, 4.0, seed=100 + idx)
        matched = any(e.event_class == cls for e in events)
        alarmed = any(e.level.value >= 2 for e in events)
        passed = (matched == expect_event) and (alarmed == expect_alarm)
        ok = ok and passed
        status = "OK " if passed else "FAIL"
        print(
            f"[{status}] {cls.value:<9} событий: {len(events):<2} "
            f"класс распознан: {'да' if matched else 'нет':<3} "
            f"тревога: {'да' if alarmed else 'нет'}"
        )
    print("Самопроверка пройдена" if ok else "Самопроверка НЕ пройдена")
    return 0 if ok else 1


def cmd_sensors(args: argparse.Namespace) -> int:
    settings = get_settings()
    site = settings.load_site()
    registry = Registry(site)
    print(f"Объект: {site.name}")
    print(f"Датчиков: {len(registry.sensors)}, зон: {len(registry.zones)}")
    print("-" * 60)
    for zone in registry.zones.values():
        print(f"Зона {zone.id} — {zone.name} ({zone.kind}), датчиков: "
              f"{len(registry.sensors_in_zone(zone.id))}")
        for sensor in registry.sensors_in_zone(zone.id):
            print(f"    [{sensor.chain_index:>2}] {sensor.id:<16} {sensor.name}"
                  f"  @ {sensor.position_m:.0f} м")
    return 0


def cmd_version(args: argparse.Namespace) -> int:
    print(f"SEISMOS {__version__}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="seismos", description="SEISMOS — контроль периметра на геофонах GS-20DX")
    parser.add_argument("--version", action="version", version=f"SEISMOS {__version__}")
    sub = parser.add_subparsers(dest="command")

    p_serve = sub.add_parser("serve", help="Запустить API и консоль оператора")
    p_serve.add_argument("--host", default=None)
    p_serve.add_argument("--port", type=int, default=None)
    p_serve.set_defaults(func=cmd_serve)

    p_sim = sub.add_parser("simulate", help="Стенд: прогон синтетического воздействия")
    p_sim.add_argument("--event", default="footstep",
                       choices=["footstep", "group", "vehicle", "digging", "climb", "impact", "weather"])
    p_sim.add_argument("--sensor", default=None)
    p_sim.add_argument("--duration", type=float, default=3.0)
    p_sim.add_argument("--seed", type=int, default=None)
    p_sim.set_defaults(func=cmd_simulate)

    p_self = sub.add_parser("selftest", help="Самопроверка конвейера обработки")
    p_self.set_defaults(func=cmd_selftest)

    p_sensors = sub.add_parser("sensors", help="Показать конфигурацию датчиков и зон")
    p_sensors.set_defaults(func=cmd_sensors)

    p_ver = sub.add_parser("version", help="Версия системы")
    p_ver.set_defaults(func=cmd_version)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
