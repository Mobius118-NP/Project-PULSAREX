import argparse
import json
import os
import socket
import time
import webbrowser
from threading import Thread
from urllib.error import URLError
from urllib.request import urlopen

from .audio import devices
from .config import Config


def running_service(url):
    try:
        with urlopen(url + "/api/session", timeout=0.5) as response:
            return json.load(response).get("service") == "pulsar-mk2"
    except (OSError, URLError, ValueError):
        return False


def open_when_ready(url, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if running_service(url):
            webbrowser.open(url)
            return
        time.sleep(0.1)


def main():
    parser = argparse.ArgumentParser(description="PULSAR Mk. II acoustic observatory")
    parser.add_argument("--config", help="TOML configuration path")
    parser.add_argument("--source", choices=["simulation", "microphone"])
    parser.add_argument("--device", type=int)
    parser.add_argument("--host", help="Default: 127.0.0.1; LAN: 0.0.0.0 (requires PULSAR_TOKEN)")
    parser.add_argument("--port", type=int)
    parser.add_argument("--list-devices", action="store_true")
    parser.add_argument(
        "--open-browser", action="store_true", help="Open the dashboard after the server is ready"
    )
    args = parser.parse_args()
    if args.list_devices:
        try:
            for device in devices():
                print(
                    f"{device['id']:3}  {device['name']}  ({device['channels']} input channels, "
                    f"{device['backend']}, {device['default_sample_rate']:g} Hz)"
                )
        except RuntimeError as exc:
            parser.error(str(exc))
        return
    try:
        cfg = Config.load(args.config)
        for key in ("source", "device", "host", "port"):
            if getattr(args, key) is not None:
                setattr(cfg, key, getattr(args, key))
        cfg.validate()
    except (OSError, ValueError, TypeError) as exc:
        parser.error(str(exc))
    import uvicorn

    from .server import create_app, is_loopback

    dashboard_host = {"0.0.0.0": "127.0.0.1", "::": "::1"}.get(cfg.host, cfg.host)
    if ":" in dashboard_host:
        dashboard_host = f"[{dashboard_host}]"
    dashboard_url = f"http://{dashboard_host}:{cfg.port}"
    if args.open_browser and running_service(dashboard_url):
        print(f"PULSAR is already running: {dashboard_url}")
        webbrowser.open(dashboard_url)
        return
    try:
        app = create_app(cfg, token=os.environ.get("PULSAR_TOKEN"))
    except ValueError as exc:
        parser.error(str(exc))
    print(f"PULSAR Mk. II | {cfg.source} | no raw audio recording")
    print(f"Dashboard: {dashboard_url}")
    if args.open_browser:
        Thread(target=open_when_ready, args=(dashboard_url,), daemon=True).start()
    if not is_loopback(cfg.host):
        try:
            addresses = sorted(
                {item[4][0] for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)}
            )
            for address in addresses:
                print(f"LAN candidate: http://{address}:{cfg.port} (access token required)")
        except OSError:
            print("LAN address unavailable; check your network adapter settings.")
    uvicorn.run(app, host=cfg.host, port=cfg.port, log_level="info", access_log=False)


if __name__ == "__main__":
    main()
