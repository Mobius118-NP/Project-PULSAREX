"""Discovery and an opt-in read-only connection selector for authorized clients."""
import json
import socket
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward a bearer credential to a redirected origin.


def lan_addresses():
    try:
        return sorted({a[4][0] for a in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
                       if not a[4][0].startswith("127.")})
    except OSError:
        return []


class EndpointSelector:
    """Prefer LAN, pin application instance, require TLS for an explicitly enabled public fallback.

    Credentials are supplied per request; never persisted. No router or server changes.
    Restore LAN after two successful probes to avoid oscillation.
    """
    def __init__(self, lan, server_id, public=None, public_enabled=False):
        for endpoint in [lan, public] if public else [lan]:
            parsed = urlparse(endpoint)
            if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("Use HTTP(S) origins without embedded credentials")
            if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
                raise ValueError("Endpoints must be origins")
        if public and urlparse(public).scheme != "https":
            raise ValueError("Public fallback requires HTTPS with certificate verification")
        self.lan, self.public, self.server_id = lan.rstrip('/'), public.rstrip('/') if public else None, server_id
        self.public_enabled = public_enabled
        self.current = None
        self.lan_successes = 0

    def select(self, probe):
        if probe(self.lan) == self.server_id:
            self.lan_successes += 1
            if self.current != self.public or not self.public or self.lan_successes >= 2:
                self.current = self.lan
                return self.current
        else:
            self.lan_successes = 0
        if self.public_enabled and self.public and probe(self.public) == self.server_id:
            self.current = self.public
            return self.current
        # Do not retain an endpoint that just failed validation.
        self.current = None
        raise ConnectionError("No authenticated endpoint matched the pinned server identity")

    def connect(self, token):
        def probe(endpoint):
            try:
                request = Request(endpoint+'/api/v1/status', headers={'Authorization': f'Bearer {token}'})
                with build_opener(NoRedirect()).open(request, timeout=2) as response:
                    return json.loads(response.read(65536)).get('server_id')
            except (OSError, ValueError):
                return None
        return self.select(probe)


class Discovery:
    def __init__(self):
        self.service = self.info = None
        self.status = "disabled"

    def start(self, config):
        if not config.mdns_enabled:
            return
        if config.host in ("127.0.0.1", "localhost", "::1"):
            self.status = "requires authenticated LAN binding; use direct loopback URL"
            return
        try:
            from zeroconf import ServiceInfo, Zeroconf
            addresses = lan_addresses()
            if not addresses:
                raise OSError("No LAN IPv4 address found")
            self.info = ServiceInfo('_pulsarex._tcp.local.', 'PULSAREX._pulsarex._tcp.local.',
                                    addresses=[socket.inet_aton(a) for a in addresses], port=config.port,
                                    server=socket.gethostname()+'.local.', properties={'schema': '1', 'auth': 'required'})
            self.service = Zeroconf()
            self.service.register_service(self.info, allow_name_change=True)
            self.status = "advertising"
        except (ImportError, OSError) as exc:
            self.status = f"unavailable: {exc}; use direct LAN IP"

    def close(self):
        if self.service:
            if self.info:
                self.service.unregister_service(self.info)
            self.service.close()
