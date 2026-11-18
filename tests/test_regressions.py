import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event, Thread
from types import SimpleNamespace

import numpy as np
import pytest
from test_api import client_for

import pulsar.engine as engine_module
from pulsar.audio import MicrophoneSource
from pulsar.baseline import Baseline
from pulsar.config import Config
from pulsar.dsp import estimate_bearing, harmonic_groups
from pulsar.engine import Engine


def test_unavailable_event_directory_does_not_prevent_startup(tmp_path, monkeypatch):
    original = engine_module.EventStore

    def storage(path):
        if str(path) != ":memory:":
            raise PermissionError("injected unavailable storage")
        return original(path)

    monkeypatch.setattr(engine_module, "EventStore", storage)
    engine = Engine(Config(data_dir=str(tmp_path)))
    try:
        engine.start()
        snapshot = wait_frame(engine)
        assert any("events are temporary" in warning for warning in snapshot["status"]["warnings"])
    finally:
        engine.close()


def wait_frame(engine, predicate=lambda snapshot: snapshot["measurement_valid"], timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snapshot = engine.snapshot()
        if predicate(snapshot):
            return snapshot
        time.sleep(0.01)
    pytest.fail(f"Expected acquisition state was not reached: {engine.snapshot()['status']}")


def test_live_controls_do_not_restart_or_discard_baseline(tmp_path):
    engine = Engine(Config(data_dir=str(tmp_path)))
    try:
        engine.start()
        before = wait_frame(engine)
        thread = engine.thread
        baseline = engine.baseline
        engine.calibrate()
        engine.configure({"event_threshold_db": 18, "baseline_adaptation": True})
        after = wait_frame(engine)
        assert engine.thread is thread
        assert engine.baseline is baseline and engine.baseline.calibrating
        assert after["stream_id"] == before["stream_id"]
        assert len(after["shift_history"]) >= len(before["shift_history"])
        assert after["config_revision"] > before["config_revision"]
        assert after["config"]["event_threshold_db"] == 18
    finally:
        engine.close()


def test_pause_marks_measurements_stale_and_resume_has_new_stream(tmp_path):
    engine = Engine(Config(data_dir=str(tmp_path)))
    try:
        engine.start()
        live = wait_frame(engine)
        engine.stop()
        stopped = engine.snapshot()
        assert not stopped["measurement_valid"]
        assert not stopped["shift"]["reliable"]
        assert not stopped["direction"]["available"]
        engine.start()
        resumed = wait_frame(engine)
        assert resumed["stream_id"] != live["stream_id"]
        assert resumed["sequence"] > live["sequence"]
    finally:
        engine.close()


def test_sample_rate_round_trip_restores_frequency_band(tmp_path):
    engine = Engine(Config(data_dir=str(tmp_path)))
    try:
        engine.configure({"sample_rate": 8000})
        assert engine.config.max_frequency == 4000
        engine.configure({"sample_rate": 48000})
        assert engine.config.max_frequency == 18000
    finally:
        engine.close()


def test_concurrent_controls_preserve_updates_and_leave_no_worker(tmp_path):
    engine = Engine(Config(data_dir=str(tmp_path)))
    try:
        engine.start()
        with ThreadPoolExecutor(max_workers=3) as pool:
            jobs = [
                pool.submit(engine.configure, change)
                for change in ({"event_threshold_db": 18}, {"zero_tolerance_hz": 5}, {"reference_hz": 1100})
            ]
            for job in jobs:
                job.result(timeout=5)
        assert engine.config.event_threshold_db == 18
        assert engine.config.zero_tolerance_hz == 5
        assert engine.config.reference_hz == 1100
        engine.stop()
        assert not engine.thread.is_alive()
    finally:
        engine.close()


def test_calibration_does_not_count_capture_gaps():
    baseline = Baseline(64, duration=1)
    baseline.calibrate(0)
    baseline.update(np.full(64, -60.0), 0)
    baseline.update(np.full(64, -60.0), 0.5)
    baseline.pause()
    baseline.update(np.full(64, -60.0), 100)
    assert baseline.progress == pytest.approx(0.5)
    assert not baseline.ready
    baseline.update(np.full(64, -60.0), 100.5)
    assert baseline.ready


@pytest.mark.parametrize("change", [-40, 40])
def test_adaptation_excludes_negative_and_narrow_changes(change):
    baseline = Baseline(64)
    baseline.ready = True
    baseline.mean.fill(-60)
    samples = np.full(64, -60.0)
    samples[0] += change
    baseline.update(samples, 1, adapt=True)
    assert np.all(baseline.mean == -60)


@pytest.mark.parametrize("broken", ["wrong-shape", "truncated"])
def test_corrupt_baseline_is_ignored(tmp_path, broken):
    path = tmp_path / "baseline.npz"
    if broken == "truncated":
        path.write_bytes(b"PK\x03\x04broken zip")
    else:
        np.savez(path, mean=np.zeros(64), m2=np.zeros(2), count=10, signature="test")
    assert not Baseline(64).load(path, "test")


def test_baseline_write_failure_does_not_stop_analysis(tmp_path, monkeypatch):
    engine = Engine(Config(data_dir=str(tmp_path)))
    engine.baseline.ready = True
    engine.baseline.dirty = True
    engine.baseline.count = 20

    def denied(*args):
        raise PermissionError("read-only test directory")

    monkeypatch.setattr(engine.baseline, "save", denied)
    try:
        engine.start()
        snapshot = wait_frame(engine)
        assert snapshot["status"]["running"] and snapshot["status"]["warnings"]
        assert snapshot["status"]["error"] is None
    finally:
        engine.close()


def test_queue_overflow_discards_oldest_input():
    source = MicrophoneSource(Config())
    for i in range(10):
        source._callback(np.full((1024, 1), float(i)), 1024, None, SimpleNamespace(input_overflow=False))
    assert source.queue.qsize() == 8
    assert source.read()[0, 0] == 2


def test_long_hop_capture_wait_can_be_cancelled_promptly():
    source = MicrophoneSource(Config(sample_rate=8000, max_frequency=4000, fft_size=32768, hop_size=32768))
    stopped = Event()
    cancelled = Event()

    def read():
        try:
            source.read(stopped)
        except InterruptedError:
            cancelled.set()

    worker = Thread(target=read)
    worker.start()
    stopped.set()
    worker.join(timeout=0.5)
    assert cancelled.is_set() and not worker.is_alive()


def test_harmonics_ignore_amplitude_order_and_duplicate_orders():
    peaks = [{"hz": 2000.0, "dbfs": -10}, {"hz": 3000.0, "dbfs": -15}, {"hz": 1000.0, "dbfs": -20}]
    groups = harmonic_groups(peaks, 12)
    assert len(groups) == 1 and groups[0]["fundamental_hz"] == 1000
    assert [p["order"] for p in groups[0]["members"]] == [1, 2, 3]
    assert harmonic_groups([{"hz": 100, "dbfs": -10}, {"hz": 110, "dbfs": -12}], 12) == []


def test_narrowband_direction_is_not_reported_as_confident():
    signal = np.sin(np.arange(4096) * 2 * np.pi * 1000 / 48000)
    channels = np.column_stack((signal, np.roll(signal, 2), np.roll(signal, 3)))
    result = estimate_bearing(channels, 48000, [[0, 0], [0.1, 0], [0, 0.1]])
    assert not result["available"] and "narrowband" in result["reason"]


@pytest.mark.parametrize(
    "changes",
    [
        {"min_frequency": True},
        {"max_frequency": float("inf")},
        {"mic_positions": "not a geometry"},
        {"mic_positions": [[0, 0], [0, 0], [1, 0], [0, 1]], "channels": 4},
    ],
)
def test_invalid_configuration_rejected_cleanly(changes):
    with pytest.raises(ValueError):
        replace(Config(), **changes).validate()


def test_logout_revokes_replayed_cookie_and_login_is_limited(tmp_path):
    with client_for(
        Config(data_dir=str(tmp_path)), token="024681", autostart=False
    ) as client:
        client.post("/api/login", json={"token": "024681"})
        cookie = client.cookies.get("pulsar_session")
        client.post("/api/logout")
        assert client.get("/api/config", headers={"Cookie": f"pulsar_session={cookie}"}).status_code == 401
        for _ in range(5):
            assert client.post("/api/login", json={"pin": "111111"}).status_code == 401
        assert client.post("/api/login", json={"pin": "111111"}).status_code == 429


def test_malformed_host_and_origin_do_not_crash_server(tmp_path):
    with client_for(Config(data_dir=str(tmp_path)), autostart=False) as client:
        assert client.get("/api/config", headers={"Host": "["}).status_code == 400
        assert client.post("/api/capture/start", headers={"Origin": "http://["}).status_code == 403


def test_event_count_is_independent_of_display_limit(tmp_path):
    with client_for(Config(data_dir=str(tmp_path)), autostart=False) as client:
        engine = client.app.state.engine
        for i in range(8):
            engine.store.add({"category": "spectral change", "change_db": i})
        result = client.get("/api/events?limit=5").json()
        assert len(result["events"]) == 5 and result["total"] == 8


def test_measurements_are_strict_json_after_live_settings_change(tmp_path):
    engine = Engine(Config(data_dir=str(tmp_path)))
    try:
        engine.start()
        wait_frame(engine)
        engine.configure({"reference_hz": 1200, "zero_tolerance_hz": 10})
        frame = wait_frame(engine, lambda snapshot: snapshot.get("shift", {}).get("reference_hz") == 1200)
        assert frame["config"]["reference_hz"] == 1200
        json.dumps(frame, allow_nan=False)
    finally:
        engine.close()
