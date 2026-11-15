import time
from types import SimpleNamespace

import pytest
from test_api import client_for

import pulsar.engine as engine_module
import pulsar.main as cli
import pulsar.server as server_module
from pulsar.audio import ManagedMicrophoneSource, SyntheticSource
from pulsar.config import Config


def test_failed_microphone_can_switch_to_working_input_without_server_restart(tmp_path, monkeypatch):
    """Exercise real REST/lifecycle recovery without opening any physical microphone."""

    class TestMicrophone(SyntheticSource):
        def __init__(self, config):
            super().__init__(config)
            self.overruns = 0
            self.last_timestamp = None
            self.device_id = config.device
            self.device_name = f"Test microphone {config.device}"
            self.backend = "test"

        def start(self, stop_event=None):
            if self.config.device == 1:
                raise RuntimeError("Injected driver failure")

        def read(self, stop_event=None):
            if stop_event.wait(0.005):
                raise InterruptedError("stopped")
            return super().read()

        def close(self):
            pass

    monkeypatch.setattr(engine_module, "MicrophoneSource", TestMicrophone)
    monkeypatch.setattr(
        server_module,
        "input_inventory",
        lambda: {
            "devices": [
                {
                    "id": 2,
                    "name": "Working test input",
                    "backend": "test",
                    "channels": 1,
                    "default_sample_rate": 48000,
                }
            ],
            "default_input": None,
            "error": None,
        },
    )
    with client_for(Config(source="microphone", device=1, data_dir=str(tmp_path))) as client:
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            failure = client.get("/api/measurements").json()
            if failure["status"]["error"]:
                break
            time.sleep(0.01)
        assert "Injected driver failure" in failure["status"]["error"]
        assert not failure["measurement_valid"]
        assert client.get("/api/devices").json()["devices"][0]["id"] == 2
        assert client.post("/api/baseline/calibrate").status_code == 409
        assert client.patch("/api/config", json={"device": 2}).status_code == 200
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            recovered = client.get("/api/measurements").json()
            if recovered["measurement_valid"]:
                break
            time.sleep(0.01)
        assert recovered["measurement_valid"], recovered["status"]
        assert recovered["status"]["error"] is None
        assert recovered["status"]["input"]["device"] == 2
        assert recovered["status"]["microphone_active"]
        assert recovered["stream_id"] != failure["stream_id"]


def test_hung_native_driver_is_terminated_on_timeout():
    source = ManagedMicrophoneSource(Config())

    class HungProcess:
        pid = 42
        alive = True
        terminated = False

        def start(self):
            pass

        def is_alive(self):
            return self.alive

        def join(self, timeout=None):
            pass

        def terminate(self):
            self.terminated = True
            self.alive = False

        def kill(self):
            self.alive = False

    process = HungProcess()
    source.context = SimpleNamespace(Process=lambda **kwargs: process)
    source.messages.close()

    class SilentPipe:
        def poll(self, timeout=0):
            time.sleep(0.005)
            return False

        def close(self):
            pass

    source.messages = SilentPipe()
    source.startup_timeout = 0.02
    try:
        with pytest.raises(RuntimeError, match="did not respond"):
            source.start()
    finally:
        source.close()
    assert process.terminated and not process.is_alive()


def test_new_device_invalidates_previous_array_geometry(tmp_path):
    engine = engine_module.Engine(
        Config(channels=3, mic_positions=[[0, 0], [0.1, 0], [0, 0.1]], data_dir=str(tmp_path))
    )
    try:
        engine.configure({"device": 2})
        assert engine.config.mic_positions == []
    finally:
        engine.close()


def test_browser_opens_only_after_readiness(monkeypatch):
    readiness = iter([False, True])
    opened = []
    monkeypatch.setattr(cli, "running_service", lambda url: next(readiness))
    monkeypatch.setattr(cli.webbrowser, "open", opened.append)
    cli.open_when_ready("http://127.0.0.1:8765", timeout=1)
    assert opened == ["http://127.0.0.1:8765"]


def test_bad_cli_options_give_a_short_error(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["pulsar", "--port", "-1"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2
    assert "Invalid port" in capsys.readouterr().err


def test_real_capture_worker_reports_invalid_device_without_capturing():
    source = ManagedMicrophoneSource(Config(source="microphone", device=999999))
    try:
        with pytest.raises(RuntimeError):
            source.start()
    finally:
        source.close()
    assert not source.process.is_alive()
