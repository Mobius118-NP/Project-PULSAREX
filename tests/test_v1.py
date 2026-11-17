from datetime import UTC, datetime

import numpy as np
import pytest
from fastapi.testclient import TestClient

from pulsar.config import Config
from pulsar.integrations import vibration_features
from pulsar.network import EndpointSelector
from pulsar.server import create_app
from pulsar.stereo import stereo_delay


def test_versioned_routes_reviews_and_schema(tmp_path):
    app = create_app(Config(data_dir=str(tmp_path)), autostart=False)
    engine = app.state.engine
    engine.baseline.ready = True
    engine.baseline.count = 20
    engine.baseline.mean.fill(-60)
    event = engine.store.add({'timestamp': '2026-11-17T00:00:00Z', 'category': 'spectral change',
                             'features': [.1, .2, -.3, .4], 'frequency_band': 'high', 'score': .7})
    with TestClient(app, base_url='http://127.0.0.1') as client:
        status = client.get('/api/v1/status').json()
        assert status['public_access'] == 'disabled' and status['server_id']
        assert client.get('/api/v1/openapi.json').json()['openapi']
        assert client.get('/api/v1/docs').status_code == 200
        assert client.post('/api/v1/baseline/save', json={'name': 'fan-operating'}).status_code == 200
        assert client.get('/api/v1/baseline/profiles').json()['profiles'] == ['fan-operating']
        assert client.post('/api/v1/baseline/freeze', json={}).json()['frozen']
        assert not client.post('/api/v1/baseline/unfreeze', json={}).json()['frozen']
        assert client.post('/api/v1/baseline/load', json={'name': '../../escape'}).status_code == 422
        assert client.post('/api/v1/baseline/load', json={'name': 'fan-operating'}).status_code == 200
        assert client.patch(f'/api/v1/events/{event["id"]}', json={'annotation': 'Reviewed pattern'}).status_code == 200
        assert client.post('/api/v1/signatures', json={'event_id': event['id'], 'label': 'test pattern'}).status_code == 201
        detail = client.get(f'/api/v1/events/{event["id"]}').json()
        assert detail['annotation'] == 'Reviewed pattern'
        assert detail['signature_comparisons'][0]['source_identity_confirmed'] is False
        assert client.get('/api/v1/events?band=low').json()['filtered_total'] == 0
        assert client.get('/api/v1/events?since=2026-11-17T00:00:00').status_code == 422
        assert client.get('/api/v1/events/999').status_code == 404
        assert client.get('/api/v1/events/export').status_code == 200
        assert client.post('/api/v1/baseline/reset').json()['calibrating']


def test_external_events_and_argos_are_separate(tmp_path):
    with TestClient(create_app(Config(data_dir=str(tmp_path)), autostart=False), base_url='http://127.0.0.1') as client:
        event = {'timestamp': datetime.now(UTC).isoformat(), 'sensor_id': 'external-1',
                 'change_db': 20, 'duration_seconds': .5, 'score': .6}
        submitted = client.post('/api/v1/events', json=event)
        assert submitted.status_code == 201
        assert submitted.json()['source'] == 'external'
        assert client.post('/api/v1/events', json={**event, 'category': 'person'}).status_code == 422
        assert client.post('/api/v1/events', json={**event, 'raw_audio': 'binary'}).status_code == 422
        visual = {'observation_id': 'test-1', 'timestamp': datetime.now(UTC).isoformat(), 'camera_id': 'camera-1',
                  'fov_center_deg': 80, 'fov_width_deg': 60, 'clock_uncertainty_ms': 30}
        assert client.post('/api/v1/integrations/argos', json=visual).status_code == 409
        client.patch('/api/v1/config', json={'argos_enabled': True})
        assert client.post('/api/v1/integrations/argos', json=visual).status_code == 201
        assert client.post('/api/v1/integrations/argos', json={**visual, 'person_identity': 'someone'}).status_code == 422
        result = client.get('/api/v1/integrations').json()
        assert len(result['argos']['visual_observations']) == 1
        with client.websocket_connect('ws://127.0.0.1/ws/live') as ws:
            message = ws.receive_json()
            assert message['schema_version'] == 1
            assert message['integrations']['argos_enabled']


def test_versioned_authentication_has_no_bypass(tmp_path):
    app = create_app(Config(host='0.0.0.0', data_dir=str(tmp_path)), token='test-only-token-01234567890', autostart=False)
    with TestClient(app, base_url='http://127.0.0.1') as client:
        for endpoint in ['status', 'spectrum', 'baseline', 'events', 'signatures', 'integrations', 'openapi.json', 'docs']:
            assert client.get('/api/v1/'+endpoint).status_code == 401
        assert client.post('/api/v1/baseline/reset').status_code == 401
        assert client.post('/api/v1/events', json={}).status_code == 401
        assert client.get('/api/v1/status', headers={'Authorization': 'Bearer test-only-token-01234567890'}).status_code == 200


def test_stereo_delay_ambiguity_and_validation():
    x = np.random.default_rng(3).normal(size=4096)
    samples = np.column_stack((x, np.roll(x, 4)))
    assert not stereo_delay(samples, 48000, .1)['available']
    result = stereo_delay(samples, 48000, .1, synchronized=True)
    assert result['available'] and result['delay_samples'] == 4
    assert len(result['possible_bearings_deg']) == 2
    assert 'Front/back' in result['ambiguity']
    assert not stereo_delay(np.column_stack((x, x*2)), 48000, .1, True)['available']
    tone = np.sin(np.arange(4096)*2*np.pi*1000/48000)
    assert not stereo_delay(np.column_stack((tone, np.roll(tone, 4))), 48000, .1, True)['available']
    assert not stereo_delay(np.zeros((4096, 2)), 48000, .1, True)['available']


def test_network_selection_pins_identity_and_recovers_lan():
    selector = EndpointSelector('http://192.168.1.2:8765', 'pinned-id', public='https://monitor.example.org', public_enabled=True)
    identities = {selector.lan: 'pinned-id', selector.public: 'pinned-id'}
    assert selector.select(identities.get) == selector.lan
    identities[selector.lan] = None
    assert selector.select(identities.get) == selector.public
    identities[selector.lan] = 'pinned-id'
    assert selector.select(identities.get) == selector.public
    assert selector.select(identities.get) == selector.lan
    identities[selector.lan] = identities[selector.public] = 'wrong-server'
    with pytest.raises(ConnectionError):
        selector.select(identities.get)
    assert selector.current is None
    with pytest.raises(ValueError):
        EndpointSelector('http://localhost', 'id', public='http://public.example')
    selector = EndpointSelector('http://localhost', 'id', public='https://public.example')
    with pytest.raises(ConnectionError):
        selector.select(lambda endpoint: None if endpoint == selector.lan else 'id')


def test_external_sensor_adapter():
    samples = np.sin(np.arange(1024)*2*np.pi*50/1024)
    result = vibration_features(samples, 1024)
    assert result['peak_hz'] == 50 and not result['acoustic_measurement']
    with pytest.raises(ValueError):
        vibration_features([float('nan')]*20, 100)


def test_nonfinite_external_measurement_is_json_validation_error(tmp_path):
    with TestClient(create_app(Config(data_dir=str(tmp_path)), autostart=False), base_url='http://127.0.0.1') as client:
        body = '{"timestamp":"2026-11-17T12:00:00Z","sensor_id":"test","change_db":NaN,"duration_seconds":1,"score":0.5}'
        result = client.post('/api/v1/events', content=body, headers={'Content-Type': 'application/json'})
        assert result.status_code == 422 and result.json()['detail']


def test_control_body_limit_and_rate_limit(tmp_path):
    app = create_app(Config(data_dir=str(tmp_path)), autostart=False)
    with TestClient(app, base_url='http://127.0.0.1') as client:
        assert client.patch('/api/v1/config', content=' '*65537,
                            headers={'Content-Type': 'application/json'}).status_code == 413
        for _ in range(119):
            assert client.post('/api/v1/baseline/freeze').status_code == 200
        assert client.post('/api/v1/baseline/freeze').status_code == 429
