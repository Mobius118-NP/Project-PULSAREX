# LAN and optional connection recovery

Default binding is 127.0.0.1. Explicit LAN binding such as 0.0.0.0 requires an
environment token of at least 16 characters. Use a random high-entropy value.
No cloud service, firewall modification, public endpoint, UPnP, router rule or
external account is configured. Plain HTTP is not confidential; use only a trusted
private LAN or an operator-managed HTTPS reverse proxy. Hostname pinning over
unencrypted HTTP does not prevent an active attacker from impersonating a server.

The status API and dashboard display hostname, candidate LAN addresses, port and
authentication state. These addresses can include inactive adapters/virtual networks;
choose the adapter shared by your authorized client. If another device cannot connect,
check network isolation, host firewall and adapter configuration yourself. Do not
open an internet-facing inbound rule as a troubleshooting shortcut.

Optional discovery: install `.[discovery]`, set `mdns_enabled = true`, and bind to
LAN with authentication. Advertisements use `_pulsarex._tcp.local.` and the host's
`<hostname>.local` name. Host allow-list validation accepts that name. mDNS may not
work across VLANs or isolated Wi-Fi, and some OS resolvers lack support. Direct IP
is always the fallback. Loopback-only servers are not advertised.

## Authorized Python client recovery

`pulsar.network.EndpointSelector` prefers LAN, verifies the server instance UUID,
performs authenticated status probes with two-second timeouts, and restores LAN
after two successful probes when currently using public fallback. Redirects are
rejected so bearer credentials are not forwarded to another origin. Tokens stay in
memory and are never stored by the selector. Configure endpoints without credentials.

```python
import os
from pulsar.network import EndpointSelector

selector = EndpointSelector(
    "http://192.168.1.20:8765",
    server_id="copy-the-UUID-from-an-authenticated-local-status-response",
    public="https://your-owned-domain.example",
    public_enabled=False,  # Enable only after securing an independently deployed monitoring endpoint.
)
endpoint = selector.connect(os.environ["PULSAR_TOKEN"])
```

This is an integration-client utility, not an automatically published dashboard.
The browser reconnects only to its same origin. A public URL is never probed unless
explicitly enabled. HTTPS uses the operating system certificate trust store.
UUID pinning supplements TLS; it does not replace certificate verification.

## Public server boundary (not implemented/deployed)

Direct public serving remains disabled and must not be enabled by merely changing
the host to a public address. A production deployment still requires reviewed
monitor-vs-administrator authorization, server identity provisioning, certificate
renewal, detailed access logging without secrets, stronger perimeter rate limits,
and a proxy allow-list excluding controls, signatures/annotations and identity
management. This release's single LAN token grants controls and is unsuitable as
a public monitoring credential. No public TLS proxy has been deployed or validated.

An operator-managed public endpoint also requires a routable IPv4/IPv6 or suitable
hosting design. CGNAT can prevent inbound access; dynamic DNS does not solve CGNAT.
Certificates, firewall/router rules, DNS and recovery need independent validation.
Neither Tailscale nor any VPN/cloud relay is mandatory.
