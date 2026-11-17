"""GUI-independent server lifecycle. Secrets stay in private process memory/IPC."""
import json
import multiprocessing as mp
import os
import signal
import socket
import subprocess
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path
from queue import Empty, Full
from threading import Thread

from .config import Config
from .network import lan_addresses


def read_settings(path):
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        return {key: data[key] for key in ('mode', 'port', 'source', 'config_path', 'open_browser') if key in data}
    except (OSError, ValueError, TypeError):
        return {}


def save_settings(path, settings):
    allowed = {key: settings[key] for key in ('mode', 'port', 'source', 'config_path', 'open_browser') if key in settings}
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps(allowed, indent=2), encoding='utf-8')
    temporary.replace(target)

def launch_config(base, mode, port, source, token):
    if mode not in ('local', 'lan'):
        raise ValueError('Choose Local or LAN mode')
    try:
        number = int(port)
    except (ValueError, TypeError) as exc:
        raise ValueError('Port must be a whole number from 1 to 65535') from exc
    if mode == 'lan' and not 16 <= len(token) <= 512:
        raise ValueError('LAN mode needs an access token of 16-512 characters; use Generate')
    return replace(base, host='0.0.0.0' if mode == 'lan' else '127.0.0.1', port=number,
                   source=source, mdns_enabled=base.mdns_enabled and mode == 'lan').validate()


def dashboard_urls(port, mode):
    local = f'http://127.0.0.1:{port}'
    addresses = lan_addresses() if mode == 'lan' else []
    # UDP connect consults the local route table; no packet is sent.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route:
            route.connect(('192.0.2.1', 9))
            primary = route.getsockname()[0]
        if primary in addresses:
            addresses.remove(primary)
            addresses.insert(0, primary)
    except OSError:
        pass
    return local, [f'http://{address}:{port}' for address in addresses]


def _server_worker(configuration, token, stopped, messages):
    """Spawn entry; never imports Tk or creates another launcher."""
    if os.name != 'nt':
        os.setsid()
    for stream in ('stdout', 'stderr'):
        if getattr(sys, stream) is None:
            setattr(sys, stream, open(os.devnull, 'w'))

    def report(state, message):
        try:
            messages.put_nowait({'state': state, 'message': message})
        except Full:
            pass

    try:
        import uvicorn

        from .server import create_app

        config = Config(**configuration).validate()
        app = create_app(config, token=token)
        if stopped.is_set():
            app.state.engine.close()
            report('stopped', 'Startup cancelled; server stopped')
            return
        server = uvicorn.Server(uvicorn.Config(
            app, host=config.host, port=config.port, log_level='warning', access_log=False,
            log_config=None, limit_concurrency=64, timeout_keep_alive=5,
            ws_max_size=1024, ws_max_queue=4))

        def supervise():
            announced = False
            parent = mp.parent_process()
            while not stopped.wait(.1):
                if parent is not None and not parent.is_alive():
                    break
                if server.started and not announced:
                    report('running', 'LAN server running' if config.host == '0.0.0.0' else 'Local server running')
                    announced = True
            server.should_exit = True

        Thread(target=supervise, name='launcher-shutdown', daemon=True).start()
        server.run()
        report('stopped', 'Server stopped; microphone capture closed')
    except (Exception, SystemExit) as exc:
        message = ('Server could not start. Check the selected port and configuration.'
                   if isinstance(exc, SystemExit) else str(exc) or 'Server startup failed')
        if token:
            message = message.replace(token, '[redacted]')
        report('failed', message[:1000])


class ServerController:
    """Nonblocking polling controller; Stop affects only the process it started."""
    def __init__(self):
        self.context = mp.get_context('spawn')
        self.process = self.stopped = self.messages = None
        self.state = 'stopped'
        self.message = 'Ready. Choose Local or LAN, then Start.'
        self.deadline = None
        self.local_url = ''
        self.lan_urls = []

    @property
    def busy(self):
        return self.process is not None

    def start(self, config, token=None):
        if self.busy:
            raise ValueError('Stop the current server before starting another')
        config.validate()
        if config.host not in ('127.0.0.1', '0.0.0.0'):
            raise ValueError('The launcher supports Local or private LAN binding')
        if config.host == '0.0.0.0' and (not token or not 16 <= len(token) <= 512):
            raise ValueError('LAN mode requires a 16-512 character access token')
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.bind((config.host, config.port))
        except OSError as exc:
            raise ValueError(f'Port {config.port} is unavailable. Choose another port or stop the existing server.') from exc
        self.local_url, self.lan_urls = dashboard_urls(config.port, 'lan' if config.host == '0.0.0.0' else 'local')
        self.stopped = self.context.Event()
        self.messages = self.context.Queue(maxsize=32)
        self.process = self.context.Process(target=_server_worker,
                                            args=(asdict(config), token, self.stopped, self.messages),
                                            name='pulsarex-server')
        try:
            self.process.start()
        except Exception:
            self.process = None
            self.messages.close()
            raise
        self.state, self.message = 'starting', 'Starting server. This may take a few seconds...'
        self.deadline = time.monotonic()+60

    def stop(self):
        if not self.busy or self.state == 'stopping':
            return
        self.stopped.set()
        self.state, self.message = 'stopping', 'Stopping capture and server...'
        self.deadline = time.monotonic()+15

    def poll(self):
        if self.messages:
            for _ in range(32):
                try:
                    status = self.messages.get_nowait()
                except Empty:
                    break
                # Stop is authoritative even if a late startup acknowledgement arrives.
                if self.state != 'stopping' or status['state'] in ('stopped', 'failed'):
                    self.state, self.message = status['state'], status['message']
        if self.process is not None:
            if not self.process.is_alive():
                self.process.join(timeout=0)
                if self.state not in ('stopped', 'stopping', 'failed'):
                    self.state, self.message = 'failed', 'Server exited before it was ready. Check configuration and port.'
                elif self.state == 'stopping':
                    self.state, self.message = 'stopped', 'Server stopped; microphone capture closed'
                self.messages.close()
                self.messages.cancel_join_thread()
                self.messages = None
                self.process.close()
                self.process = None
            elif self.state == 'starting' and time.monotonic() > self.deadline:
                self.stop()
                self.message = 'Startup timed out. Stopping the server...'
            elif self.state == 'stopping' and time.monotonic() > self.deadline:
                self._terminate_tree()
                self.deadline = time.monotonic()+5
                self.message = 'Unresponsive server process tree terminated; finishing cleanup...'
        return self.state, self.message

    def _terminate_tree(self):
        if os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(self.process.pid), '/T', '/F'],
                           capture_output=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    def close(self):
        self.stop()
        deadline = time.monotonic()+22
        while self.busy and time.monotonic() < deadline:
            self.poll()
            time.sleep(.05)
        if self.busy:
            raise RuntimeError('Server cleanup is still in progress')
