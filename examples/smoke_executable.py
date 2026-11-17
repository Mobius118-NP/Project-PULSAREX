"""Verify a frozen server with a sanitized environment and no physical audio capture."""
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen


def smoke(executable, directory):
    executable = Path(executable).resolve()
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        port = reservation.getsockname()[1]
    environment = {k: v for k, v in os.environ.items() if k.upper() not in ('PYTHONPATH', 'PYTHONHOME', 'VIRTUAL_ENV')}
    environment['PATH'] = str(Path(os.environ['SystemRoot'])/'System32')
    base = f'http://127.0.0.1:{port}'
    def request(path, method='GET', payload=None):
        data = json.dumps(payload).encode() if payload is not None else (b'' if method == 'POST' else None)
        req = Request(base+path, data=data, method=method, headers={'Content-Type': 'application/json'})
        with urlopen(req, timeout=3) as response:
            body = response.read()
            return json.loads(body) if response.headers.get_content_type() == 'application/json' else body
    started = time.monotonic()
    with (directory/'server.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen([str(executable), '--port', str(port), '--data-dir', str(directory/'data')],
                                   cwd=directory, env=environment, stdout=log, stderr=log,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            while True:
                if process.poll() is not None:
                    raise RuntimeError('Packaged server exited: '+(directory/'server.log').read_text())
                try:
                    status = request('/api/v1/status')
                    break
                except OSError:
                    if time.monotonic()-started > 30:
                        raise TimeoutError('Packaged server startup exceeded 30 seconds') from None
                    time.sleep(.1)
            startup_seconds = time.monotonic()-started
            assert b'Acoustic spectrum' in request('/')
            assert b'renderResearch' in request('/research.js')
            deadline = time.monotonic()+12
            while not request('/api/v1/baseline')['ready']:
                if time.monotonic() > deadline:
                    raise TimeoutError('Automatic calibration did not complete')
                time.sleep(.1)
            assert request('/api/v1/spectrum')['measurement_valid']
            request('/api/v1/config', 'PATCH', {'channels': 2, 'stereo_spacing_m': .15, 'stereo_axis_deg': 45})
            deadline = time.monotonic()+5
            while True:
                paired = request('/api/v1/spectrum')
                if paired.get('measurement_valid') and paired.get('direction', {}).get('mode') == 'two_microphone':
                    break
                if time.monotonic() > deadline:
                    raise TimeoutError('Two-microphone demo did not publish a bearing pair')
                time.sleep(.1)
            assert len(paired['direction']['possible_bearings_deg']) == 2
            assert paired['direction']['bearing_deg'] is None and paired['direction']['simulated']
            assert not paired['stereo']['available']  # UI simulation never invents a measured delay.
            deadline = time.monotonic()+12
            while not request('/api/v1/baseline')['ready']:
                if time.monotonic() > deadline:
                    raise TimeoutError('Two-channel calibration did not complete')
                time.sleep(.1)
            request('/api/v1/baseline/save', 'POST', {'name': 'packaged-demo'})
            assert request('/api/v1/baseline/freeze', 'POST', {})['frozen']
            assert not request('/api/v1/capture/stop', 'POST')['running']
            assert not request('/api/v1/spectrum')['measurement_valid']
            request('/api/v1/config', 'PATCH', {'source': 'microphone', 'device': 999999})
            request('/api/v1/capture/start', 'POST')
            deadline = time.monotonic()+12
            while not request('/api/v1/status')['status']['error']:
                if time.monotonic() > deadline:
                    raise TimeoutError('Invalid-device error not surfaced')
                time.sleep(.1)
            request('/api/v1/config', 'PATCH', {'source': 'simulation', 'device': None})
            deadline = time.monotonic()+5
            while not request('/api/v1/spectrum')['measurement_valid']:
                if time.monotonic() > deadline:
                    raise TimeoutError('Recovery to simulation failed')
                time.sleep(.1)
            request('/api/v1/capture/stop', 'POST')
            return {'startup_seconds': round(startup_seconds, 3), 'outside_venv': True,
                    'auto_calibration': True, 'static_dashboard': True, 'pause_resume': True,
                    'frozen_microphone_worker_error_recovery': True, 'two_microphone_pair': True,
                    'server_id': status['server_id'],
                    'distribution_bytes': sum(p.stat().st_size for p in executable.parent.rglob('*') if p.is_file())}
        finally:
            process.terminate()
            process.wait(timeout=10)


if __name__ == '__main__':
    print(json.dumps(smoke(sys.argv[1], sys.argv[2]), indent=2))
