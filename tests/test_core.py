import json
import math
import time
from dataclasses import replace

import numpy as np
import pytest

from pulsar.audio import SyntheticSource
from pulsar.baseline import Baseline
from pulsar.config import Config
from pulsar.dsp import Analyzer, estimate_bearing, shift_color
from pulsar.engine import Engine
from pulsar.storage import EventDetector, EventStore


def tone(hz, cfg, amplitude=0.4):
    return amplitude * np.sin(2 * np.pi * hz * np.arange(cfg.fft_size) / cfg.sample_rate)


@pytest.mark.parametrize("hz", [100, 440, 1000, 1234.5, 8000])
def test_fft_frequency_and_level(hz):
    cfg = Config()
    result = Analyzer(cfg).analyze(tone(hz, cfg))
    assert result["peaks"][0]["hz"] == pytest.approx(hz, abs=1.5)
    assert result["rms_dbfs"] == pytest.approx(20 * math.log10(0.4 / math.sqrt(2)), abs=0.1)
    assert len(result["frequencies"]) == cfg.display_bins
    json.dumps(result, allow_nan=False)


def test_harmonic_series_and_stability():
    cfg = Config()
    analyzer = Analyzer(cfg)
    signal = tone(1000, cfg) + tone(2000, cfg, 0.15) + tone(3000, cfg, 0.08)
    result = analyzer.analyze(signal)
    group = result["harmonics"][0]
    assert group["fundamental_hz"] == pytest.approx(1000, abs=1)
    assert [p["order"] for p in group["members"]] == [1, 2, 3]
    assert analyzer.analyze(signal)["harmonics"][0]["stability"]


def test_silence_has_no_valid_shift():
    result = Analyzer(Config()).analyze(np.zeros(4096))
    assert not result["shift"]["reliable"]
    assert result["shift"]["hz"] is None
    assert not result["peaks"]


@pytest.mark.parametrize("hz", [920, 1000, 1080])
def test_signed_shift(hz):
    cfg = Config()
    shift = Analyzer(cfg).analyze(tone(hz, cfg))["shift"]
    assert shift["reliable"]
    assert shift["hz"] == pytest.approx(hz - 1000, abs=1)


def test_ambiguous_tones_not_reliable():
    cfg = Config()
    shift = Analyzer(cfg).analyze(tone(940, cfg) + tone(1080, cfg))["shift"]
    assert shift["status"] == "ambiguous"
    assert not shift["reliable"]


def test_gradient_continuity_and_saturation():
    def rgb(value):
        color = shift_color(value)
        return np.array([int(color[i : i + 2], 16) for i in (1, 3, 5)])

    assert shift_color(0) == shift_color(2) == shift_color(-2)
    for value in (-200, -101, -2, 0, 2, 101, 200):
        assert np.max(np.abs(rgb(value - 0.001) - rgb(value + 0.001))) <= 1
    assert shift_color(200) == shift_color(20000)
    assert shift_color(-200) == shift_color(-20000)
    assert shift_color(None) == shift_color(float("nan"))


def test_baseline_calibration_persistence_and_signature(tmp_path):
    baseline = Baseline(64, duration=1)
    baseline.calibrate(0)
    for now in np.linspace(0, 1, 20):
        baseline.update(np.full(64, -60.0), now)
    assert baseline.ready
    assert np.max(baseline.update(np.full(64, -40.0), 2)) == pytest.approx(20)
    baseline.save(tmp_path / "baseline.npz", "test")
    restored = Baseline(64)
    assert restored.load(tmp_path / "baseline.npz", "test")
    assert not Baseline(64).load(tmp_path / "baseline.npz", "other input")
    baseline.update(np.full(64, -10.0), 3, adapt=True)
    assert baseline.mean[0] == pytest.approx(-60)


@pytest.mark.parametrize("sign", [1, -1])
def test_events_cooldown_and_disappearance(sign):
    cfg = Config()
    frame = Analyzer(cfg).analyze(tone(1000, cfg))
    frame["flux"] = 0.8
    detector = EventDetector(12, 3)
    assert detector.detect(frame, np.zeros(cfg.display_bins), True, 0, "now") is None
    deviation = np.full(cfg.display_bins, 20 * sign)
    event = detector.detect(frame, deviation, True, 1, "now")
    assert event and event["change_db"] == 20
    assert detector.detect(frame, deviation, True, 2, "later") is None
    assert detector.detect(frame, deviation, True, 5, "later")


def test_event_storage_retention(tmp_path):
    store = EventStore(tmp_path / "test.db", retention=3)
    for i in range(7):
        store.add({"category": "spectral change", "change_db": i})
    assert [e["change_db"] for e in store.recent()] == [6, 5, 4]
    assert store.recent(category="missing") == []
    store.close()


def test_array_bearing_broadband():
    cfg = Config()
    rng = np.random.default_rng(4)
    raw = rng.normal(size=cfg.fft_size + 256)
    geometry = np.array([[0, 0], [0.12, 0], [0, 0.12]])
    bearing = 60
    direction = np.array([np.sin(np.deg2rad(bearing)), np.cos(np.deg2rad(bearing))])
    indices = np.arange(cfg.fft_size) + 64
    signals = np.column_stack(
        [
            np.interp(indices + position @ direction / 343 * cfg.sample_rate, np.arange(len(raw)), raw)
            for position in geometry
        ]
    )
    result = estimate_bearing(signals, cfg.sample_rate, geometry)
    assert result["available"], result
    assert result["bearing_deg"] == pytest.approx(bearing, abs=5)
    assert not estimate_bearing(signals[:, :1], cfg.sample_rate, [])["available"]


@pytest.mark.parametrize(
    "changes",
    [
        {"fft_size": 1023},
        {"channels": 0},
        {"reference_hz": float("nan")},
        {"zero_tolerance_hz": 300},
        {"event_threshold_db": True},
        {"mic_positions": [[0, 0], [1, 0], [2, 0]], "channels": 3},
    ],
)
def test_invalid_config(changes):
    with pytest.raises(ValueError):
        replace(Config(), **changes).validate()


def test_synthetic_source_continuity():
    cfg = Config()
    source = SyntheticSource(cfg)
    first = source.read()
    second = source.read()
    assert first.shape == (cfg.hop_size, 1)
    assert np.isfinite(second).all()
    assert abs(float(first[-1, 0] - second[0, 0])) < 0.15


def test_engine_lifecycle_and_bounded_history(tmp_path):
    engine = Engine(Config(data_dir=str(tmp_path)))
    try:
        engine.start()
        deadline = time.monotonic() + 3
        while engine.sequence < 2 and time.monotonic() < deadline:
            time.sleep(0.02)
        snapshot = engine.snapshot()
        assert snapshot["sequence"] >= 2, snapshot
        assert snapshot["direction"]["simulated"]
        assert not snapshot["status"]["microphone_active"]
        json.dumps(snapshot, allow_nan=False)
        engine.stop()
        assert not engine.capture
        engine.configure({"sample_rate": 16000})
        assert engine.config.max_frequency == 8000
        engine.start()
        assert engine.shift_history.maxlen == 240
    finally:
        engine.close()
