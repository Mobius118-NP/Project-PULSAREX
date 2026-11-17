import socket
import time
from dataclasses import replace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from pulsar.config import Config
from pulsar.launcher_service import ServerController, launch_config, read_settings, save_settings


def port():
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        return reservation.getsockname()[1]


def wait_state(controller, expected, timeout=20):
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        controller.poll()
        if controller.state == expected and (expected != 'stopped' or not controller.busy):
            return
        if controller.state == 'failed':
            pytest.fail(controller.message)
        time.sleep(.03)
    pytest.fail(f'Launcher state {controller.state}: {controller.message}')


def test_launcher_lan_config_and_token_validation(tmp_path):
    base = Config(data_dir=str(tmp_path))
    lan = launch_config(base, 'lan', '8765', 'simulation', 'test-only-token-123456789')
    assert lan.host == '0.0.0.0' and lan.port == 8765
    assert base.host == '127.0.0.1'
    local = launch_config(base, 'local', '8876', 'microphone', '')
    assert local.host == '127.0.0.1' and local.source == 'microphone'
    for args in [('lan', '8765', 'simulation', ''), ('local', 'text', 'simulation', ''),
                 ('local', '0', 'simulation', ''), ('public', '8765', 'simulation', ''),
                 ('lan', '8765', 'simulation', 'x'*513)]:
        with pytest.raises(ValueError):
            launch_config(base, *args)


def test_launcher_settings_never_store_credentials(tmp_path):
    path = tmp_path/'settings.json'
    save_settings(path, {'mode': 'lan', 'port': 8765, 'source': 'simulation',
                         'token': 'a-secret-that-must-not-be-written', 'open_browser': False})
    assert 'secret' not in path.read_text() and 'token' not in path.read_text()
    assert read_settings(path)['mode'] == 'lan'
    path.write_text('{broken json')
    assert read_settings(path) == {}


def test_launcher_refuses_occupied_port_without_starting_process(tmp_path):
    controller = ServerController()
    with socket.socket() as occupied:
        occupied.bind(('127.0.0.1', 0))
        occupied.listen()
        cfg = Config(port=occupied.getsockname()[1], data_dir=str(tmp_path))
        with pytest.raises(ValueError, match='unavailable'):
            controller.start(cfg)
    assert not controller.busy


def test_launcher_local_process_start_stop_and_port_release(tmp_path):
    controller = ServerController()
    try:
        cfg = Config(port=port(), data_dir=str(tmp_path))
        controller.start(cfg)
        wait_state(controller, 'running')
        with urlopen(controller.local_url+'/api/v1/status', timeout=3) as response:
            assert response.status == 200
        controller.stop()
        wait_state(controller, 'stopped')
        with socket.socket() as probe:
            assert probe.connect_ex(('127.0.0.1', cfg.port)) != 0
    finally:
        controller.close()


def test_launcher_lan_process_requires_authentication(tmp_path):
    controller = ServerController()
    token = 'test-only-launcher-token-0123456789'
    try:
        cfg = Config(host='0.0.0.0', port=port(), data_dir=str(tmp_path))
        controller.start(cfg, token)
        wait_state(controller, 'running')
        with pytest.raises(HTTPError) as failure:
            urlopen(controller.local_url+'/api/v1/status', timeout=3)
        assert failure.value.code == 401
        request = Request(controller.local_url+'/api/v1/status', headers={'Authorization': 'Bearer '+token})
        with urlopen(request, timeout=3) as response:
            assert response.status == 200
        assert all(f':{cfg.port}' in link for link in controller.lan_urls)
    finally:
        controller.close()


def test_launcher_can_cancel_startup_and_restart(tmp_path):
    controller = ServerController()
    try:
        cfg = Config(port=port(), data_dir=str(tmp_path))
        controller.start(cfg)
        controller.stop()
        wait_state(controller, 'stopped')
        controller.start(replace(cfg, port=port()))
        wait_state(controller, 'running')
    finally:
        controller.close()
