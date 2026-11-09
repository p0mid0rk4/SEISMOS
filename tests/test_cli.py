"""Тесты командной строки SEISMOS."""

from __future__ import annotations

from seismos.cli.main import build_parser, cmd_selftest, cmd_version


def test_version_command(capsys):
    assert cmd_version(None) == 0
    out = capsys.readouterr().out
    assert "SEISMOS" in out


def test_parser_has_core_commands():
    parser = build_parser()
    args = parser.parse_args(["simulate", "--event", "vehicle", "--duration", "2"])
    assert args.command == "simulate"
    assert args.event == "vehicle"
    assert args.duration == 2.0


def test_selftest_passes(capsys):
    # Самопроверка работает без оборудования на эталонных сигналах.
    code = cmd_selftest(None)
    out = capsys.readouterr().out
    assert "Самопроверка" in out
    assert code == 0
