"""Bounded requests and shared PIN-attempt limits for local/LAN access."""
import hmac
import secrets
import time
from collections import OrderedDict, deque
from threading import RLock

from starlette.responses import JSONResponse


def valid_pin(value):
    return isinstance(value, str) and len(value) == 6 and value.isascii() and value.isdigit()


def generate_pin():
    return f'{secrets.randbelow(1_000_000):06d}'


class PinAttempts:
    """One atomic budget shared by login, HTTP bearer access and WebSocket handshakes."""
    def __init__(self, clock=None):
        self.clock = clock or time.monotonic
        self.clients = OrderedDict()
        self.global_failures = deque(maxlen=30)
        self.lock = RLock()
        self.window = 300

    def verify(self, client, candidate, expected):
        with self.lock:
            now = self.clock()
            while self.global_failures and now-self.global_failures[0] >= self.window:
                self.global_failures.popleft()
            history = self.clients.get(client, deque(maxlen=5))
            while history and now-history[0] >= self.window:
                history.popleft()
            if len(history) >= 5 or len(self.global_failures) >= 30:
                return 'limited'
            if hmac.compare_digest(candidate.encode('utf-8'), expected.encode('utf-8')):
                self.clients.pop(client, None)
                return 'ok'
            if client not in self.clients and len(self.clients) >= 256:
                self.clients.popitem(last=False)
            self.clients[client] = history
            history.append(now)
            self.global_failures.append(now)
            return 'invalid'


class RequestBodyLimit:
    def __init__(self, app, limit=65536):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['method'] not in ('POST', 'PATCH', 'PUT', 'DELETE'):
            return await self.app(scope, receive, send)
        chunks, size = [], 0
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            body = message.get('body', b'')
            size += len(body)
            if size > self.limit:
                response = JSONResponse({'detail': 'Control request exceeds 64 KiB'}, status_code=413)
                return await response(scope, receive, send)
            chunks.append(body)
            if not message.get('more_body', False):
                break
        delivered = False
        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {'type': 'http.request', 'body': b''.join(chunks), 'more_body': False}
            return await receive()
        await self.app(scope, replay, send)
