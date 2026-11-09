"""Тесты конвейера обнаружения и классификатора."""

from __future__ import annotations

import numpy as np

from seismos.core.models import EventClass
from seismos.detection.classifier import Classifier, ClassifierFeatures
from seismos.detection.dsp import BandPass, rms, spectral_features, zero_crossing_rate
from seismos.detection.staltl import STALTA, CfarDetector, SeismicDetector
from seismos.hardware.simulator import SeismicSignalGenerator


def test_stalta_rises_on_amplitude_jump():
    sta_lta = STALTA(sta_len=32, lta_len=512)
    ratio_quiet = 0.0
    for _ in range(600):
        ratio_quiet = sta_lta.update(1.0)
    for _ in range(60):
        ratio_loud = sta_lta.update(20.0)
    assert ratio_loud > ratio_quiet
    assert ratio_loud > 3.0


def test_cfar_detects_above_noise_floor():
    cfar = CfarDetector(ref=32, guard=4, alpha=4.0)
    for _ in range(100):
        cfar.update(1.0)
    hit, ratio = cfar.update(10.0)
    assert hit
    assert ratio > 4.0


def test_bandpass_reduces_out_of_band_energy():
    fs = 1000
    t = np.arange(4000) / fs
    low = np.sin(2 * np.pi * 2 * t)     # ниже полосы
    high = np.sin(2 * np.pi * 300 * t)  # выше полосы
    bp = BandPass(fs, 5.0, 120.0)
    out_low = bp.process(low)
    bp.reset()
    out_high = bp.process(high)
    assert rms(out_low[500:]) < 0.1
    assert rms(out_high[500:]) < 0.1


def test_spectral_features_finds_dominant_frequency():
    fs = 1000
    t = np.arange(2000) / fs
    x = np.sin(2 * np.pi * 40 * t)
    dom, _centroid, spectrum = spectral_features(x, fs)
    assert abs(dom - 40.0) < 3.0
    assert spectrum.size > 0


def test_zero_crossing_rate_increases_with_frequency():
    fs = 1000
    t = np.arange(2000) / fs
    low = zero_crossing_rate(np.sin(2 * np.pi * 10 * t))
    high = zero_crossing_rate(np.sin(2 * np.pi * 100 * t))
    assert high > low


def test_detector_triggers_on_footstep():
    gen = SeismicSignalGenerator(sample_rate=1000, seed=11)
    det = SeismicDetector(sample_rate=1000)
    signal = gen.background(2.5)
    signal = np.concatenate([signal, gen.footstep(1.5), gen.background(2.0)])
    triggered = False
    ended = False
    for start in range(0, signal.size, 128):
        res = det.process(signal[start:start + 128])
        triggered = triggered or res.triggered
        ended = ended or res.ended
    assert triggered
    assert ended


def test_detector_quiet_on_background():
    gen = SeismicSignalGenerator(sample_rate=1000, noise_microns=0.5, seed=12)
    det = SeismicDetector(sample_rate=1000)
    bg = gen.background(4.0)
    events = 0
    for start in range(0, bg.size, 128):
        res = det.process(bg[start:start + 128])
        if res.ended:
            events += 1
    assert events == 0


def test_classifier_identifies_impact_and_vehicle():
    clf = Classifier()
    impact, conf_i = clf.classify(ClassifierFeatures(
        duration_s=0.15, peak=60.0, rms=20.0, dominant_hz=95.0, centroid_hz=95.0,
        zcr=0.4, ratio=8.0))
    assert impact == EventClass.IMPACT
    assert conf_i > 0.3

    vehicle, _ = clf.classify(ClassifierFeatures(
        duration_s=4.0, peak=40.0, rms=15.0, dominant_hz=11.0, centroid_hz=12.0,
        zcr=0.05, ratio=6.0))
    assert vehicle == EventClass.VEHICLE


def test_classifier_returns_none_for_empty_features():
    clf = Classifier()
    cls, conf = clf.classify(ClassifierFeatures())
    assert cls == EventClass.NONE
    assert conf == 0.0


def test_detector_closes_after_hold_window():
    gen = SeismicSignalGenerator(sample_rate=1000, seed=21)
    det = SeismicDetector(sample_rate=1000)
    signal = np.concatenate([gen.background(2.5), gen.footstep(1.0), gen.background(3.0)])
    ended_count = 0
    for start in range(0, signal.size, 128):
        if det.process(signal[start:start + 128]).ended:
            ended_count += 1
    # Импульсы шагов склеиваются в одно событие, а не дробятся на много.
    assert ended_count == 1


def test_detector_reports_features_on_event():
    gen = SeismicSignalGenerator(sample_rate=1000, seed=31)
    det = SeismicDetector(sample_rate=1000)
    signal = np.concatenate([gen.background(2.5), gen.vehicle(4.0), gen.background(2.0)])
    final = None
    for start in range(0, signal.size, 128):
        res = det.process(signal[start:start + 128])
        if res.ended:
            final = res
    assert final is not None
    assert final.dominant_hz > 0.0
    assert final.peak > 0.0
    assert final.duration_s > 0.0
    assert "core_s" in final.features

