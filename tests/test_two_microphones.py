import json
import time
from dataclasses import replace

import numpy as np
import pytest
from fastapi.testclient import TestClient

from pulsar.config import Config
from pulsar.direction import direction_measurement
from pulsar.engine import Engine
from pulsar.server import create_app
from pulsar.stereo import stereo_delay


def distance(a, b):
    return abs((a-b+180) % 360-180)


def signals(bearing, axis=90, spacing=.15, rate=48000):
    rng = np.random.default_rng(9)
    raw = rng.normal(size=4608)
    indices = np.arange(4096)+256
    delay = -spacing*np.cos(np.deg2rad(bearing-axis))/343*rate
    return np.column_stack((raw[indices], np.interp(indices-delay, np.arange(len(raw)), raw)))


@pytest.mark.parametrize('bearing,axis', [(25, 90), (150, 90), (220, 90), (310, 90), (60, 0), (200, 45), (359, 90)])
def test_two_mics_recover_true_bearing_and_mirror(bearing, axis):
    result = stereo_delay(signals(bearing, axis), 48000, .15, True, axis)
    assert result['available'], result
    assert min(distance(b, bearing) for b in result['possible_bearings_deg']) < 3
    mirrored = (2*axis-bearing) % 360
    assert min(distance(b, mirrored) for b in result['possible_bearings_deg']) < 3
    assert result['bearing_deg'] is None, 'Never arbitrarily choose one of the ambiguous bearings'
    assert 0 < result['uncertainty_deg'] <= 180
    assert all(0 <= b < 360 for b in result['possible_bearings_deg'])
    json.dumps(result, allow_nan=False)


def test_two_position_geometry_rotates_bearing():
    samples = signals(200, axis=0)
    result = stereo_delay(samples, 48000, .9, True, 90, [[0, 0], [0, .15]])
    assert result['spacing_m'] == pytest.approx(.15)
    assert result['axis_bearing_deg'] == pytest.approx(0)
    assert min(distance(b, 200) for b in result['possible_bearings_deg']) < 3
    Config(channels=2, mic_positions=[[0, 0], [0, .15]]).validate()


@pytest.mark.parametrize('positions', [[[0, 0], [0, 0]], [[0, 0], [0, .001]], [[0, 0]], [[0, 0], [0, float('nan')]]])
def test_invalid_pair_geometry(positions):
    with pytest.raises(ValueError):
        Config(channels=2, mic_positions=positions).validate()


def test_single_channel_unsynchronized_and_duplicate_input_unavailable():
    pair = signals(25)
    cfg = Config(source='microphone', channels=2)
    assert not direction_measurement(pair, cfg, 0)[0]['available']
    assert not direction_measurement(pair[:, :1], replace(cfg, channels=1), 0)[0]['available']
    mono = np.column_stack((pair[:, 0], -2*pair[:, 0]))
    assert not stereo_delay(mono, 48000, .15, True)['available']


def test_live_engine_direction_path_uses_two_mics_and_clears_stale_pair(tmp_path):
    cfg = Config(source='microphone', channels=2, stereo_synchronized=True,
                 stereo_spacing_m=.15, data_dir=str(tmp_path))
    direction, stereo = direction_measurement(signals(25), cfg, 0)
    assert direction['available'] and direction['mode'] == 'two_microphone'
    assert stereo['available']
    engine = Engine(cfg)
    try:
        engine.latest = {'direction': direction, 'stereo': stereo, 'shift': {'reliable': False}}
        stopped = engine.snapshot()
        assert not stopped['direction']['available'] and not stopped['stereo']['available']
        engine.configure({'device': 3})
        assert not engine.config.stereo_synchronized
    finally:
        engine.close()


def test_simulation_two_mic_pair_is_explicit_and_has_no_fabricated_delay(tmp_path):
    cfg = Config(channels=2, data_dir=str(tmp_path))
    direction, stereo = direction_measurement(np.zeros((4096, 2)), cfg, 10)
    assert direction['simulated'] and len(direction['possible_bearings_deg']) == 2
    assert not stereo['available'] and 'delay_seconds' not in stereo


def test_api_two_mic_settings_and_stream_format(tmp_path):
    app = create_app(Config(data_dir=str(tmp_path)), autostart=False)
    with TestClient(app, base_url='http://127.0.0.1') as client:
        response = client.patch('/api/v1/config', json={'channels': 2, 'stereo_synchronized': True,
                                'stereo_spacing_m': .15, 'stereo_axis_deg': 30,
                                'mic_positions': [[0, 0], [.1, .1]]})
        assert response.status_code == 200, response.text
        assert response.json()['stereo_synchronized']
        assert client.patch('/api/v1/config', json={'stereo_axis_deg': 360}).status_code == 422
        assert client.patch('/api/v1/config', json={'stereo_spacing_m': 0}).status_code == 422
        cfg = replace(app.state.engine.config, source='microphone')
        pair, stereo = direction_measurement(signals(25, axis=45, spacing=np.sqrt(.02)), cfg, 0)
        app.state.engine.latest = {'direction': pair, 'stereo': stereo, 'shift': {'reliable': False}}
        with client.websocket_connect('ws://127.0.0.1/ws/live') as ws:
            frame = ws.receive_json()
            assert not frame['direction']['available']  # Acquisition stopped; historical pair must not appear live.


@pytest.mark.parametrize('rate,spacing', [(0, .1), (48000, 0), (float('nan'), .1), (48000, float('inf'))])
def test_bad_estimator_parameters_are_unavailable(rate, spacing):
    assert not stereo_delay(signals(25), rate, spacing, True)['available']


def test_two_channel_demo_stream_has_pair_and_bounded_history(tmp_path):
    app = create_app(Config(channels=2, data_dir=str(tmp_path)))
    with TestClient(app, base_url='http://127.0.0.1') as client:
        deadline = time.monotonic()+4
        while client.get('/api/v1/spectrum').json()['sequence'] < 2:
            assert time.monotonic() < deadline
            time.sleep(.02)
        with client.websocket_connect('ws://127.0.0.1/ws/live') as ws:
            frame = ws.receive_json()
            assert frame['direction']['mode'] == 'two_microphone'
            assert len(frame['direction']['possible_bearings_deg']) == 2
            assert frame['direction']['simulated'] and frame['direction']['bearing_deg'] is None
            assert all(len(point['possible_bearings_deg']) == 2 for point in frame['bearing_history'])
        assert app.state.engine.bearing_history.maxlen == 120
        client.post('/api/v1/capture/stop')
        stopped = client.get('/api/v1/spectrum').json()
        assert not stopped['direction']['available'] and not stopped['stereo']['available']
