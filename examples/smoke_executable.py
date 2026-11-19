"""Verify a frozen server with a sanitized environment and no physical audio capture."""
import argparse
import json
import os
import socket
import subprocess
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import Request, urlopen


def smoke(executable, directory, *, onefile=False, camera=None):
    executable = Path(executable).resolve()
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        port = reservation.getsockname()[1]
    environment = {k: v for k, v in os.environ.items() if k.upper() not in (
        'PYTHONPATH', 'PYTHONHOME', 'VIRTUAL_ENV', 'PULSAR_PIN', 'PULSAR_TOKEN', 'TCL_LIBRARY', 'TK_LIBRARY',
    )}
    environment['PATH'] = str(Path(os.environ['SystemRoot'])/'System32')
    extraction = None
    if onefile:
        profile = directory/'empty-profile'
        profile.mkdir(exist_ok=True)
        extraction = TemporaryDirectory(prefix='pulsarex-smoke-')
        environment.update(USERPROFILE=str(profile), LOCALAPPDATA=str(profile/'AppData/Local'),
                           TEMP=extraction.name, TMP=extraction.name)
    base = f'http://127.0.0.1:{port}'
    def request(path, method='GET', payload=None):
        data = json.dumps(payload).encode() if payload is not None else (b'' if method == 'POST' else None)
        req = Request(base+path, data=data, method=method, headers={'Content-Type': 'application/json'})
        with urlopen(req, timeout=3) as response:
            body = response.read()
            return json.loads(body) if response.headers.get_content_type() == 'application/json' else body
    started = time.monotonic()
    startup_timeout = 240 if onefile else 60
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
                    if time.monotonic()-started > startup_timeout:
                        raise TimeoutError(f'Packaged server startup exceeded {startup_timeout} seconds') from None
                    time.sleep(.1)
            startup_seconds = time.monotonic()-started
            assert b'Acoustic spectrum' in request('/')
            assert b'renderResearch' in request('/research.js')
            if onefile:
                assert b'--chassis-black' in request('/terminal.css')
                assert request('/fonts/IBMPlexSans.ttf').startswith(b'\x00\x01\x00\x00')
                assert request('/fonts/IBMPlexMono-Regular.ttf').startswith(b'\x00\x01\x00\x00')
                assert Path(request('/api/v1/vision')['default_root']) == profile/'ARGOS'
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
            before = request('/api/v1/events')['total']
            cleared = request('/api/v1/events', 'DELETE', {'confirm': True})
            assert cleared['deleted'] >= before and request('/api/v1/events')['total'] == 0
            if camera is not None:
                request('/api/v1/vision/start', 'POST', {'camera': camera, 'identity': True})
                try:
                    deadline = time.monotonic()+40
                    while time.monotonic() < deadline:
                        vision = request('/api/v1/vision')
                        if vision['error']:
                            raise RuntimeError(vision['error'])
                        if not vision['stale']:
                            break
                        time.sleep(.2)
                    else:
                        raise TimeoutError('ARGOS camera did not publish a fresh frame')
                    assert vision['identity_status'].startswith('Recognition ready')
                    assert request('/api/v1/vision/frame')['jpeg_base64']
                    assert request('/api/v1/vision/catalogue')['identities'] == []
                finally:
                    assert not request('/api/v1/vision/stop', 'POST')['running']
            return {'startup_seconds': round(startup_seconds, 3), 'outside_venv': True,
                    'auto_calibration': True, 'static_dashboard': True, 'pause_resume': True,
                    'frozen_microphone_worker_error_recovery': True, 'two_microphone_pair': True,
                    'archive_clear': True, 'packaged_fonts': onefile,
                    'argos_camera_with_recognition_loaded': camera is not None,
                    'server_id': status['server_id'],
                    'distribution_bytes': executable.stat().st_size if onefile else
                    sum(p.stat().st_size for p in executable.parent.rglob('*') if p.is_file())}
        finally:
            if onefile and process.poll() is None:
                # The one-file bootloader has a separate application process.
                subprocess.run([str(Path(environment['PATH'])/'taskkill.exe'), '/T', '/F', '/PID', str(process.pid)],
                               capture_output=True, timeout=10)
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=10)
            if extraction:
                extraction.cleanup()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('executable')
    parser.add_argument('directory')
    parser.add_argument('--onefile', action='store_true')
    parser.add_argument('--camera', type=int, help='Optional consent-based test of a local camera index')
    args = parser.parse_args()
    print(json.dumps(smoke(args.executable, args.directory, onefile=args.onefile, camera=args.camera), indent=2))
