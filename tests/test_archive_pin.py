import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from pulsar.config import Config
from pulsar.security import PinAttempts, generate_pin, valid_pin
from pulsar.server import create_app
from pulsar.storage import EventStore, EventWriter


def test_six_digit_pin_generation_preserves_leading_zeroes(monkeypatch):
    monkeypatch.setattr('pulsar.security.secrets.randbelow', lambda maximum: 7)
    assert generate_pin() == '000007'
    assert valid_pin('000000') and valid_pin('024681')
    for invalid in ('12345', '1234567', '12a456', '１２３４５６', ' 12345', 123456, None):
        assert not valid_pin(invalid)


def test_pin_attempt_budget_is_atomic_shared_and_expires():
    now = [0.]
    attempts = PinAttempts(clock=lambda: now[0])
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(lambda _: attempts.verify('one-client', '111111', '024681'), range(20)))
    assert results.count('invalid') == 5
    assert results.count('limited') == 15
    assert attempts.verify('one-client', '024681', '024681') == 'limited'
    # Rotating addresses cannot bypass the server-wide budget.
    for client in range(5):
        for _ in range(5):
            assert attempts.verify(str(client), '111111', '024681') == 'invalid'
    assert attempts.verify('fresh-client', '024681', '024681') == 'limited'
    assert len(attempts.global_failures) == 30
    now[0] = 301
    assert attempts.verify('one-client', '024681', '024681') == 'ok'


def test_pin_login_api_and_websocket_share_guess_limits(tmp_path):
    app = create_app(Config(host='0.0.0.0', data_dir=str(tmp_path)), token='024681', autostart=False)
    with TestClient(app, base_url='http://127.0.0.1') as client:
        assert client.post('/api/login', json={'pin': '024681'}).status_code == 200
        saved_cookie = client.cookies.get('pulsar_session')
        client.cookies.clear()
        for _ in range(3):
            assert client.post('/api/login', json={'pin': '111111'}).status_code == 401
        for _ in range(2):
            assert client.get('/api/config', headers={'Authorization': 'Bearer 111111'}).status_code == 401
        assert client.post('/api/login', json={'pin': '024681'}).status_code == 429
        assert client.get('/api/config', headers={'Authorization': 'Bearer 024681'}).status_code == 429
        assert not client.get('/api/session', headers={'Authorization': 'Bearer 024681'}).json()['authenticated']
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect('/ws', headers={'Authorization': 'Bearer 024681'}):
                pass
        # Existing random session credentials continue to work during PIN lockout.
        client.cookies.set('pulsar_session', saved_cookie)
        assert client.get('/api/config').status_code == 200
        assert client.post('/api/logout').status_code == 200
        assert client.get('/api/config').status_code == 401


def test_non_pin_server_credentials_rejected(tmp_path):
    for invalid in ('old-long-access-token', '12345', '１２３４５６'):
        with pytest.raises(ValueError, match='six digits'):
            create_app(Config(data_dir=str(tmp_path)), token=invalid, autostart=False)


def test_clear_archive_keeps_signatures_and_never_reuses_event_ids(tmp_path):
    path = tmp_path/'events.sqlite3'
    store = EventStore(path)
    old = store.add({'event_id': 'before', 'category': 'spectral change', 'features': [.1, .2]})
    store.annotate(old['id'], 'old annotation')
    store.save_signature(old['id'], 'Reviewed synthetic example')
    assert store.clear() == 1
    assert store.count() == 0 and len(store.signatures()) == 1
    with pytest.raises(KeyError):
        store.get(old['id'])
    new = store.add({'event_id': 'after', 'category': 'spectral change'})
    assert new['id'] > old['id']
    store.clear()
    store.close()
    restored = EventStore(path)
    try:
        assert restored.add({'category': 'spectral change'})['id'] > new['id']
    finally:
        restored.close()


def test_clear_barrier_prevents_queued_old_event_resurrection(tmp_path, monkeypatch):
    store = EventStore(tmp_path/'events.sqlite3')
    blocked, release = Event(), Event()
    original_add = store.add

    def slow_add(event):
        if event['event_id'] == 'old-in-flight':
            blocked.set()
            release.wait(5)
        return original_add(event)

    monkeypatch.setattr(store, 'add', slow_add)
    writer = EventWriter(store, {}, capacity=8)
    try:
        writer.submit({'event_id': 'old-in-flight'})
        assert blocked.wait(2)
        writer.submit({'event_id': 'old-queued'})
        clearing = writer.request_clear()
        writer.submit({'event_id': 'new-after-boundary'})
        release.set()
        assert clearing.result() == 2
        writer.close()
        assert [event['event_id'] for event in store.recent()] == ['new-after-boundary']
    finally:
        release.set()
        writer.close()
        store.close()


def test_clear_api_requires_auth_confirmation_and_preserves_baseline(tmp_path):
    app = create_app(Config(host='0.0.0.0', data_dir=str(tmp_path)), token='024681', autostart=False)
    engine = app.state.engine
    engine.store.add({'event_id': 'old', 'category': 'spectral change'})
    baseline = engine.baseline
    engine.detector.active = {'event_id': 'old'}
    with TestClient(app, base_url='http://127.0.0.1') as client:
        assert client.request('DELETE', '/api/v1/events', json={'confirm': True}).status_code == 401
        client.post('/api/login', json={'pin': '024681'})
        assert client.delete('/api/v1/events').status_code == 422
        assert client.request('DELETE', '/api/v1/events', json={'confirm': False}).status_code == 422
        assert client.request('DELETE', '/api/v1/events', json={'confirm': True, 'padding': 'x'*70000}).status_code == 413
        assert engine.store.count() == 1
        assert client.request('DELETE', '/api/v1/events', json={'confirm': True},
                              headers={'Origin': 'https://untrusted.example'}).status_code == 403
        response = client.request('DELETE', '/api/v1/events', json={'confirm': True})
        assert response.status_code == 200 and response.json()['deleted'] == 1
        assert client.get('/api/events').json()['total'] == 0
        assert engine.baseline is baseline and engine.detector.active is None


def test_clear_api_reports_storage_failure_without_success(tmp_path, monkeypatch):
    app = create_app(Config(data_dir=str(tmp_path)), autostart=False)
    app.state.engine.store.add({'category': 'spectral change'})

    def fail():
        raise sqlite3.OperationalError('synthetic disk failure')

    monkeypatch.setattr(app.state.engine.store, 'clear', fail)
    with TestClient(app, base_url='http://127.0.0.1') as client:
        assert client.request('DELETE', '/api/v1/events', json={'confirm': True}).status_code == 503
        assert app.state.engine.store.count() == 1
