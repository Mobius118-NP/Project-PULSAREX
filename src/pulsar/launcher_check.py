"""Packaged launcher IPC check; no real microphone capture and no token output."""
import json
import socket
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from .config import Config
from .launcher_service import ServerController
from .security import generate_pin


def main(destination):
    output = Path(destination).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    controller = ServerController()
    token = generate_pin()
    started = time.monotonic()
    try:
        # Tcl assets must work from inside the bundle, not from a host Python.
        import tkinter
        tcl_version = tkinter.Tcl().eval('info patchlevel')
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0))
            port = reservation.getsockname()[1]
        config = Config(host='0.0.0.0', port=port, data_dir=str(output.parent/'launcher-check-data'))
        controller.start(config, token)
        while controller.poll()[0] != 'running':
            if controller.state == 'failed' or time.monotonic()-started > 65:
                raise RuntimeError(controller.message)
            time.sleep(.05)
        opener = build_opener(ProxyHandler({}))
        endpoint = controller.local_url+'/api/v1/status'
        try:
            opener.open(endpoint, timeout=3)
            raise AssertionError('LAN API accepted an unauthenticated request')
        except HTTPError as error:
            assert error.code == 401
        request = Request(endpoint, headers={'Authorization': 'Bearer '+token})
        with opener.open(request, timeout=3) as response:
            assert response.status == 200
        controller.close()
        with socket.socket() as probe:
            assert probe.connect_ex(('127.0.0.1', port)) != 0
        result = {'passed': True, 'tcl_version': tcl_version, 'frozen_server_spawn': True,
                  'lan_authentication': True, 'graceful_stop': True, 'port_released': True,
                  'elapsed_seconds': round(time.monotonic()-started, 3), 'physical_microphone_capture': False}
    except Exception as exc:
        result = {'passed': False, 'error': str(exc).replace(token, '[redacted]')}
        raise
    finally:
        controller.close()
        output.write_text(json.dumps(result, indent=2), encoding='utf-8')
