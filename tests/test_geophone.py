"""Тесты модели геофона GS-20DX и генератора сигналов."""

from __future__ import annotations

import numpy as np

from seismos.core.models import EventClass
from seismos.hardware.geophone import GS20DX, GeophoneModel, GS20DXSpec
from seismos.hardware.simulator import SeismicSignalGenerator


def test_spec_defaults():
    spec = GS20DXSpec()
    assert spec.natural_frequency_hz == 4.5
    assert spec.sensitivity_v_per_m_s == 28.8
    assert spec.coil_resistance_ohm == 375.0


def test_voltage_velocity_roundtrip():
    model = GS20DX()
    velocity = np.array([1e-3, 2e-3, 5e-3])
    volts = velocity * model.spec.sensitivity_v_per_m_s
    back = model.voltage_to_velocity(volts)
    assert np.allclose(back, velocity)


def test_microns_conversion():
    model = GS20DX()
    v = np.array([1e-6, 2.5e-6])
    mkm = model.velocity_to_microns(v)
    assert np.allclose(mkm, [1.0, 2.5])


def test_magnitude_response_normalized_above_resonance():
    model = GeophoneModel(GS20DXSpec(), sample_rate=1000)
    freqs = np.linspace(20.0, 200.0, 200)
    resp = model.magnitude_response(freqs)
    # Выше собственной частоты отклик по скорости стремится к 1
    assert np.allclose(resp, 1.0, atol=0.1)
    # Ниже собственной частоты отклик существенно подавлен
    low = model.magnitude_response(np.array([1.0]))
    assert low[0] < 0.1


def test_apply_response_shapes_signal():
    model = GeophoneModel(sample_rate=1000)
    velocity = np.sin(2 * np.pi * 20 * np.arange(2000) / 1000.0) * 1e-4
    volts = model.apply_response(velocity)
    assert volts.shape == velocity.shape
    assert np.max(np.abs(volts)) > 0


def test_temperature_and_tilt_checks():
    model = GS20DX()
    assert model.within_temperature(20.0)
    assert not model.within_temperature(120.0)
    assert model.check_tilt(1.0)
    assert not model.check_tilt(10.0)


def test_generator_background_noise_level():
    gen = SeismicSignalGenerator(noise_microns=1.0, seed=1)
    bg = gen.background(2.0)
    assert bg.size == 2000
    assert 0.5 < float(np.std(bg)) < 1.8


def test_generator_vehicle_more_energetic_than_footstep():
    gen = SeismicSignalGenerator(seed=2)
    vehicle = gen.vehicle(3.0)
    footstep = gen.footstep(3.0)
    assert np.sqrt(np.mean(vehicle**2)) > np.sqrt(np.mean(footstep**2))


def test_generator_by_class_matches_requested():
    gen = SeismicSignalGenerator(seed=3)
    for cls in [EventClass.FOOTSTEP, EventClass.VEHICLE, EventClass.DIGGING,
                EventClass.CLIMB, EventClass.IMPACT]:
        sig = gen.by_class(cls, 2.0)
        assert sig.size > 0
        assert np.max(np.abs(sig)) > 1.0


def test_stream_places_events_in_time():
    gen = SeismicSignalGenerator(seed=4)
    stream = gen.stream(duration_s=5.0, events=[(2.0, EventClass.IMPACT)])
    assert stream.size == 5000
    early = np.max(np.abs(stream[:1000]))
    late = np.max(np.abs(stream[2000:2100]))
    assert late > early
