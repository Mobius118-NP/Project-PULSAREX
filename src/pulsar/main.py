import argparse
import os
import socket

from .audio import devices
from .config import Config


def main():
    parser = argparse.ArgumentParser(description="PULSAR Mk. II acoustic observatory")
    parser.add_argument("--config", help="TOML configuration path")
    parser.add_argument("--source", choices=["simulation", "microphone"])
    parser.add_argument("--device", type=int)
    parser.add_argument("--host", help="Default: 127.0.0.1; LAN: 0.0.0.0 (requires PULSAR_TOKEN)")
    parser.add_argument("--port", type=int)
    parser.add_argument("--list-devices", action="store_true")
    args = parser.parse_args()
    if args.list_devices:
        for device in devices():
            print(f"{device['id']:3}  {device['name']}  ({device['channels']} input channels)")
        return
    cfg = Config.load(args.config)
    for key in ("source", "device", "host", "port"):
        if getattr(args, key) is not None:
            setattr(cfg, key, getattr(args, key))
    cfg.validate()
    import uvicorn

    from .server import create_app, is_loopback

    try:
        app = create_app(cfg, token=os.environ.get("PULSAR_TOKEN"))
    except ValueError as exc:
        parser.error(str(exc))
    print(f"PULSAR Mk. II | {cfg.source} | no raw audio recording")
    print(f"Dashboard: http://{'127.0.0.1' if not is_loopback(cfg.host) else cfg.host}:{cfg.port}")
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
