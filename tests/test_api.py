import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from pulsar.config import Config
from pulsar.server import create_app


@pytest.fixture
def cfg(tmp_path):
    return Config(data_dir=str(tmp_path))


def client_for(cfg, **kwargs):
    return TestClient(create_app(cfg, **kwargs), base_url="http://127.0.0.1")


def test_measurements_controls_and_static_dashboard(cfg):
    with client_for(cfg) as client:
        assert client.get("/").status_code == 200
        assert "Acoustic spectrum" in client.get("/").text
        assert client.get("/app.js").status_code == 200
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            frame = client.get("/api/measurements").json()
            if frame["sequence"] > 0:
                break
            time.sleep(0.02)
        assert frame["schema_version"] == 1 and frame["sequence"] > 0
        assert client.post("/api/baseline/calibrate").json()["calibrating"]
        assert client.post("/api/capture/stop").json()["running"] is False
        assert client.post("/api/baseline/calibrate").status_code == 409
        assert client.post("/api/capture/start").json()["running"]
        assert client.patch("/api/config", json={"zero_tolerance_hz": 1000}).status_code == 422
        assert client.patch("/api/config", json={"host": "0.0.0.0"}).status_code == 422
        assert client.patch("/api/config", json={"sample_rate": 16000}).status_code == 200


def test_lan_requires_token(cfg):
    with pytest.raises(ValueError):
        create_app(replace(cfg, host="0.0.0.0"))


def test_auth_cookie_bearer_and_logout(cfg):
    token = "test-only-high-entropy-access-token"
    with client_for(replace(cfg, host="0.0.0.0"), token=token, autostart=False) as client:
        assert client.get("/api/session").json()["authenticated"] is False
        assert client.get("/api/config").status_code == 401
        assert client.post("/api/login", json={"token": "wrong"}).status_code == 401
        assert client.post("/api/login", json={"token": "🤔"}).status_code == 401
        assert client.post("/api/login", json={"token": token}).status_code == 200
        assert client.get("/api/config").status_code == 200
        client.post("/api/logout")
        assert client.get("/api/config").status_code == 401
        assert client.get("/api/config", headers={"Authorization": "Bearer " + token}).status_code == 200


def test_cross_origin_and_unrecognized_host_rejected(cfg):
    with client_for(cfg, autostart=False) as client:
        assert (
            client.post("/api/capture/start", headers={"Origin": "https://untrusted.example"}).status_code
            == 403
        )
        assert client.get("/api/config", headers={"Host": "untrusted.example"}).status_code == 400


def test_websocket_schema_and_origin(cfg):
    with client_for(cfg) as client:
        with client.websocket_connect("ws://127.0.0.1/ws", headers={"Origin": "http://127.0.0.1"}) as ws:
            frame = ws.receive_json()
            assert frame["type"] == "measurement"
            assert frame["schema_version"] == 1
            assert frame["status"]["clients"] >= 1
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                "ws://127.0.0.1/ws", headers={"Origin": "https://untrusted.example"}
            ):
                pass


def test_websocket_authentication(cfg):
    with client_for(cfg, token="test-only-high-entropy-access-token", autostart=False) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("ws://127.0.0.1/ws"):
                pass


def test_event_export_is_processed_data(cfg):
    app = create_app(cfg, autostart=False)
    app.state.engine.store.add(
        {
            "timestamp": "2026-11-15T16:00:00Z",
            "category": "spectral change",
            "band_hz": [100, 200],
            "change_db": 15,
            "duration_seconds": 0.1,
            "score": 0.7,
            "source": "simulation",
        }
    )
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert len(client.get("/api/events").json()["events"]) == 1
        assert client.get("/api/events?category=missing").json()["events"] == []
        assert client.get("/api/events?limit=99999").status_code == 422
        exported = client.get("/api/events/export")
        assert "spectral change" in exported.text and "audio" not in exported.text
        assert exported.headers["content-type"].startswith("text/csv")
