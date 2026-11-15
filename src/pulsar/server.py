import asyncio
import csv
import hmac
import io
import ipaddress
import secrets
import socket
import time
from collections import OrderedDict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from threading import RLock
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .audio import input_inventory
from .engine import Engine


def is_loopback(host):
    return host == "localhost" or (host and _ip_loopback(host))


def _ip_loopback(host):
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def equal_secret(left, right):
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


class Login(BaseModel):
    token: str = Field(min_length=1, max_length=512)


def create_app(config, token=None, autostart=True):
    require_auth = not is_loopback(config.host) or bool(token)
    if require_auth and (not token or len(token) < 16):
        raise ValueError("LAN mode requires PULSAR_TOKEN containing at least 16 characters")
    sessions = OrderedDict()
    attempts = OrderedDict()
    auth_lock = RLock()
    engine = Engine(config)

    @asynccontextmanager
    async def lifespan(app):
        if autostart:
            engine.start()
        try:
            yield
        finally:
            await asyncio.to_thread(engine.close)

    app = FastAPI(
        title="PULSAR Mk. II",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.engine = engine
    app.state.require_auth = require_auth

    def authorized(connection):
        if not require_auth:
            return True
        bearer = connection.headers.get("authorization", "")
        if equal_secret(bearer, f"Bearer {token}"):
            return True
        cookie = connection.cookies.get("pulsar_session", "")
        with auth_lock:
            expiry = sessions.get(cookie, 0)
            if expiry <= time.monotonic():
                sessions.pop(cookie, None)
                return False
            return True

    def origin_valid(connection):
        origin = connection.headers.get("origin")
        if not origin:
            return True  # Non-browser clients still require auth in LAN mode.
        try:
            parsed = urlparse(origin)
            return (
                parsed.scheme in ("http", "https")
                and parsed.hostname is not None
                and parsed.netloc == connection.headers.get("host")
            )
        except ValueError:
            return False

    def host_valid(connection):
        try:
            host = urlparse("//" + connection.headers.get("host", "")).hostname
        except ValueError:
            return False
        if is_loopback(host) or host in {config.host, socket.gethostname().lower()}:
            return True
        if not require_auth:
            return False
        try:
            return ipaddress.ip_address(host).is_private
        except (ValueError, TypeError):
            return False

    @app.middleware("http")
    async def security(request, call_next):
        if not host_valid(request):
            return JSONResponse({"detail": "Unrecognized host"}, status_code=400)
        if request.method not in ("GET", "HEAD", "OPTIONS") and not origin_valid(request):
            return JSONResponse({"detail": "Cross-origin control rejected"}, status_code=403)
        if request.url.path.startswith("/api/") and request.url.path not in ("/api/session", "/api/login"):
            if not authorized(request):
                return JSONResponse({"detail": "Authentication required"}, status_code=401)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        return response

    @app.get("/api/session")
    def session_status(request: Request):
        return {
            "authenticated": authorized(request),
            "required": require_auth,
            "service": "pulsar-mk2",
            "version": __version__,
        }

    @app.post("/api/login")
    def login(body: Login, request: Request):
        key = request.client.host if request.client else "unknown"
        now = time.monotonic()
        with auth_lock:
            while len(attempts) >= 256 and key not in attempts:
                attempts.popitem(last=False)
            history = attempts.setdefault(key, deque(maxlen=8))
            while history and now - history[0] > 60:
                history.popleft()
            if len(history) >= 8:
                raise HTTPException(429, "Too many login attempts; retry in one minute")
        if require_auth and not equal_secret(body.token, token):
            with auth_lock:
                history.append(now)
            raise HTTPException(401, "Incorrect access token")
        session = secrets.token_urlsafe(32)
        with auth_lock:
            attempts.pop(key, None)
            sessions[session] = now + 28800
            while len(sessions) > 128:
                sessions.popitem(last=False)
        response = JSONResponse({"authenticated": True})
        response.set_cookie(
            "pulsar_session",
            session,
            httponly=True,
            samesite="strict",
            max_age=28800,
            secure=request.url.scheme == "https",
        )
        return response

    @app.post("/api/logout")
    def logout(request: Request):
        with auth_lock:
            sessions.pop(request.cookies.get("pulsar_session", ""), None)
        response = JSONResponse({"authenticated": False})
        response.delete_cookie("pulsar_session")
        return response

    @app.get("/api/config")
    def get_config():
        return engine.config.public()

    @app.patch("/api/config")
    async def set_config(changes: dict):
        try:
            await asyncio.to_thread(engine.configure, changes)
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        return engine.config.public()

    @app.get("/api/devices")
    async def get_devices():
        try:
            return await asyncio.to_thread(input_inventory)
        except RuntimeError as exc:
            return {"devices": [], "default_input": None, "error": str(exc)}

    @app.get("/api/measurements")
    def measurements():
        return engine.snapshot()

    @app.post("/api/capture/{action}")
    async def capture(action: str):
        if action not in ("start", "stop"):
            raise HTTPException(404, "Unknown action")
        try:
            await asyncio.to_thread(engine.start if action == "start" else engine.stop)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        return engine.snapshot()["status"]

    @app.post("/api/baseline/calibrate")
    def calibrate():
        try:
            engine.calibrate()
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return engine.baseline.status()

    @app.get("/api/events")
    def events(limit: int = Query(100, ge=1, le=5000), category: str | None = None):
        return {"events": engine.store.recent(limit, category), "total": engine.store.count()}

    @app.get("/api/events/export")
    def export_events():
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            ["id", "timestamp", "category", "band_hz", "change_db", "duration_seconds", "score", "source"]
        )
        for event in engine.store.recent(5000):
            writer.writerow(
                [
                    event.get(key)
                    for key in (
                        "id",
                        "timestamp",
                        "category",
                        "band_hz",
                        "change_db",
                        "duration_seconds",
                        "score",
                        "source",
                    )
                ]
            )
        return Response(
            output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="pulsar-events.csv"'},
        )

    @app.websocket("/ws")
    async def websocket(websocket: WebSocket):
        if not host_valid(websocket) or not origin_valid(websocket) or not authorized(websocket):
            await websocket.close(code=1008)
            return
        await websocket.accept()
        engine.clients += 1
        try:
            while True:
                if not authorized(websocket):
                    await websocket.close(code=1008)
                    break
                await asyncio.wait_for(websocket.send_json(engine.snapshot()), timeout=2)
                await asyncio.sleep(1 / engine.config.update_hz)
        except (TimeoutError, WebSocketDisconnect, RuntimeError):
            pass
        finally:
            engine.clients -= 1

    dashboard = Path(__file__).parent / "dashboard"
    app.mount("/", StaticFiles(directory=dashboard, html=True), name="dashboard")
    return app
