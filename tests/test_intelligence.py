import json
from threading import Event

import numpy as np
import pytest

from pulsar.baseline import Baseline, Profiles
from pulsar.config import Config
from pulsar.dsp import Analyzer
from pulsar.engine import Engine
from pulsar.events import EventDetector
from pulsar.storage import EventStore, EventWriter


def signal(cfg, hz=180, extra=None, noise_seed=1):
    t = np.arange(cfg.fft_size)/cfg.sample_rate
    rng = np.random.default_rng(noise_seed)
    x = rng.normal(0, .0002, len(t))
    if hz:
        x += .1*np.sin(2*np.pi*hz*t) + .04*np.sin(2*np.pi*hz*2*t)
    if extra:
        x += .04*np.sin(2*np.pi*extra*t)
    return x


def calibrated():
    cfg = Config()
    analyzer = Analyzer(cfg)
    baseline = Baseline(cfg.fft_size//2+1, duration=1)
    baseline.calibrate(0)
    for i, now in enumerate(np.linspace(0, 1, 40)):
        frame = analyzer.analyze(signal(cfg, noise_seed=i))
        baseline.update(frame['_linear_dbfs'], now)
    return cfg, analyzer, baseline


def test_robust_calibration_resists_outliers_and_is_bounded():
    baseline = Baseline(64, duration=1)
    baseline.calibrate(0)
    for i in range(1001):
        baseline.update(np.full(64, -10 if i % 10 == 0 else -60), i/1000)
    assert baseline.ready
    assert baseline.mean == pytest.approx(np.full(64, -60))
    assert baseline.samples.shape == (512, 64)
    assert baseline.scale.min() >= 2


@pytest.mark.parametrize('scenario', ['added_tone', 'upper_edge_tone', 'stopped_fan', 'changed_speed', 'low_increase', 'broadband'])
def test_fan_baseline_and_anomaly_evidence(scenario):
    cfg, analyzer, baseline = calibrated()
    detector = EventDetector()
    normal = analyzer.analyze(signal(cfg))
    assert detector.detect(normal, baseline.update(normal['_linear_dbfs'], 2), True, 2, 'normal', baseline.scale) is None
    if scenario == 'added_tone':
        samples = signal(cfg, extra=7200)
    elif scenario == 'upper_edge_tone':
        samples = signal(cfg, extra=17950)
    elif scenario == 'stopped_fan':
        samples = signal(cfg, hz=None)
    elif scenario == 'changed_speed':
        samples = signal(cfg, hz=230)
    elif scenario == 'low_increase':
        samples = signal(cfg, extra=80)
    else:
        samples = signal(cfg) + np.random.default_rng(3).normal(0, .1, cfg.fft_size)
    frame = analyzer.analyze(samples)
    prior = baseline.mean.copy()
    delta = baseline.update(frame['_linear_dbfs'], 3, adapt=True)
    assert baseline.mean == pytest.approx(prior), 'Do not absorb the event'
    event = detector.detect(frame, delta, True, 3, 'event', baseline.scale)
    assert event, scenario
    assert event['evidence']['changed_bins'] > 0
    if scenario == 'added_tone':
        assert event['frequency_band'] == 'high'
        assert any(abs(p['hz']-180) < 2 for p in frame['peaks']), 'Fan must remain in original data'
    if scenario == 'stopped_fan':
        assert event['signed_change_db'] < 0
    json.dumps(event, allow_nan=False)


def test_adaptation_is_time_based_and_suppressed_for_events():
    baseline = Baseline(64, adaptation_seconds=10)
    baseline.ready = True
    baseline.mean.fill(-60)
    for now in np.linspace(0, 10, 101):
        baseline.update(np.full(64, -59), now, adapt=True)
    assert -60 < baseline.mean[0] < -59
    before = baseline.mean.copy()
    baseline.update(np.full(64, -20), 11, adapt=True)
    assert baseline.mean == pytest.approx(before)
    assert baseline.adaptation_suppressed
    baseline.frozen = True
    baseline.update(np.full(64, -59), 12, adapt=True)
    assert baseline.mean == pytest.approx(before)


def test_profiles_and_event_lifecycle(tmp_path):
    cfg, analyzer, baseline = calibrated()
    profiles = Profiles(tmp_path/'profiles')
    profiles.save('fan-on', baseline, 'input')
    assert profiles.names() == ['fan-on']
    assert profiles.load('fan-on', baseline.bins, 1, 'input').mean == pytest.approx(baseline.mean)
    with pytest.raises(ValueError):
        profiles.load('../outside', baseline.bins, 1, 'input')
    with pytest.raises(ValueError):
        profiles.load('fan-on', baseline.bins, 1, 'other')
    detector = EventDetector()
    frame = analyzer.analyze(signal(cfg, extra=7200))
    delta = baseline.update(frame['_linear_dbfs'], 2)
    store = EventStore(tmp_path/'events.db')
    try:
        first = store.add(detector.detect(frame, delta, True, 2, 'start', baseline.scale))
        later = store.add(detector.detect(frame, delta, True, 6, 'later', baseline.scale))
        assert first['id'] == later['id'] and store.count() == 1
        assert 'persistent' in later['temporal_characteristics']
        store.annotate(first['id'], 'Reviewed fan experiment')
        normal = analyzer.analyze(signal(cfg))
        ended = detector.detect(normal, baseline.update(normal['_linear_dbfs'], 7), True, 7, 'end', baseline.scale)
        stored = store.add(ended)
        assert stored['state'] == 'completed' and stored['duration_seconds'] == 4
        assert stored['annotation'] == 'Reviewed fan experiment'
        store.save_signature(first['id'], 'test tone')
        assert store.compare(first['id'])[0]['feature_distance'] == 0
        assert store.compare(first['id'])[0]['source_identity_confirmed'] is False
    finally:
        store.close()


def test_noise_false_positives_and_added_tone_misses():
    cfg, analyzer, baseline = calibrated()
    false_positives = misses = 0
    for i in range(40, 80):
        normal = analyzer.analyze(signal(cfg, noise_seed=i))
        detector = EventDetector()
        false_positives += detector.detect(normal, baseline.update(normal['_linear_dbfs'], i),
                                           True, i, 'normal', baseline.scale) is not None
        added = analyzer.analyze(signal(cfg, extra=7200, noise_seed=i))
        misses += detector.detect(added, baseline.update(added['_linear_dbfs'], i+.1),
                                  True, i+.1, 'tone', baseline.scale) is None
    assert false_positives == 0
    assert misses == 0


def test_slow_event_storage_is_bounded_and_does_not_block_dsp():
    started, release = Event(), Event()
    saved = []
    class SlowStore:
        def add(self, event):
            started.set()
            assert release.wait(3)
            saved.append(event)
    warnings = {}
    writer = EventWriter(SlowStore(), warnings, capacity=1)
    try:
        writer.submit({'id': 1})
        assert started.wait(1)
        writer.submit({'id': 2})
        writer.submit({'id': 3})
        assert writer.queue.qsize() == 1 and writer.dropped == 1
        assert 'Slow storage' in warnings['event_queue']
    finally:
        release.set()
        writer.close()
    assert [e['id'] for e in saved] == [1, 2]


def test_stream_gap_preserves_interrupted_event(tmp_path):
    engine = Engine(Config(data_dir=str(tmp_path)))
    try:
        engine.detector.active = {'event_id': 'test-gap', 'category': 'spectral change',
                                  'timestamp': '2026-11-17T12:00:00Z', 'duration_seconds': 2.0}
        engine._reset_continuity()
        engine.writer.queue.join()
        event = engine.store.recent()[0]
        assert event['state'] == 'interrupted' and event['duration_seconds'] == 2.0
        assert engine.detector.active is None
    finally:
        engine.close()
