import asyncio
import csv
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
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import AliasChoices, BaseModel, Field

from . import __version__
from .api import install_api
from .audio import input_inventory
from .engine import Engine
from .integrations import IntegrationHub
from .network import Discovery
from .security import PinAttempts, RequestBodyLimit, valid_pin
from .vision import VisionService


def is_loopback(host):
    return host == "localhost" or (host and _ip_loopback(host))


def _ip_loopback(host):
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class Login(BaseModel):
    pin: str = Field(min_length=6, max_length=6, pattern=r'^[0-9]{6}$',
                     validation_alias=AliasChoices('pin', 'token'))


def create_app(config, token=None, autostart=True):
    require_auth = not is_loopback(config.host) or bool(token)
    if require_auth and not valid_pin(token):
        raise ValueError("LAN mode requires PULSAR_PIN containing exactly six digits (0-9)")
    sessions = OrderedDict()
    attempts = PinAttempts()
    controls = OrderedDict()
    auth_lock = RLock()
    engine = Engine(config)
    hub = IntegrationHub()
    discovery = Discovery()
    vision = VisionService()
    identity_path = Path(config.data_dir) / "server-id.txt"
    try:
        identity_path.parent.mkdir(parents=True, exist_ok=True)
        if not identity_path.exists():
            identity_path.write_text(str(uuid4()), encoding="utf-8")
        server_id = identity_path.read_text(encoding="utf-8").strip()
    except OSError:
        server_id = str(uuid4())

    @asynccontextmanager
    async def lifespan(app):
        await asyncio.to_thread(discovery.start, config)
        if autostart:
            engine.start()
        try:
            yield
        finally:
            await asyncio.to_thread(vision.stop)
            await asyncio.to_thread(engine.close)
            await asyncio.to_thread(discovery.close)

    app = FastAPI(
        title="PULSAR Mk. II",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.engine = engine
    app.state.vision = vision
    app.add_middleware(RequestBodyLimit)
    app.state.require_auth = require_auth

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Omit submitted input (which may contain credentials or non-JSON NaN values).
        return JSONResponse({"detail": [{"loc": e["loc"], "msg": e["msg"], "type": e["type"]}
                                        for e in exc.errors()]}, status_code=422)

    def authentication(connection):
        if not require_auth:
            return 'ok'
        cookie = connection.cookies.get("pulsar_session", "")
        with auth_lock:
            expiry = sessions.get(cookie, 0)
            if expiry > time.monotonic():
                return 'ok'
            sessions.pop(cookie, None)
        bearer = connection.headers.get('authorization', '')
        if not bearer:
            return 'invalid'
        key = connection.client.host if connection.client else 'unknown'
        # Cache HTTP results only. WebSockets must recheck revoked/expired sessions.
        if connection.scope['type'] == 'http' and '_pulsar_auth' in connection.scope:
            return connection.scope['_pulsar_auth']
        result = attempts.verify(key, bearer.removeprefix('Bearer '), token) if bearer.startswith('Bearer ') else attempts.verify(key, '', token)
        if connection.scope['type'] == 'http':
            connection.scope['_pulsar_auth'] = result
        return result

    def authorized(connection):
        return authentication(connection) == 'ok'

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
        if is_loopback(host) or host in {config.host, socket.gethostname().lower(), socket.gethostname().lower()+".local"}:
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
            access = authentication(request)
            if access != 'ok':
                return JSONResponse({'detail': 'Too many PIN attempts; retry in five minutes' if access == 'limited' else 'Authentication required'},
                                    status_code=429 if access == 'limited' else 401,
                                    headers={'Retry-After': '300'} if access == 'limited' else None)
            if request.method in ("POST", "PATCH", "PUT", "DELETE"):
                key = request.client.host if request.client else "unknown"
                now = time.monotonic()
                with auth_lock:
                    while len(controls) >= 256 and key not in controls:
                        controls.popitem(last=False)
                    history = controls.setdefault(key, deque(maxlen=120))
                    while history and now-history[0] > 60:
                        history.popleft()
                    if len(history) >= 120:
                        return JSONResponse({"detail": "Control rate exceeded; retry shortly"}, status_code=429)
                    history.append(now)
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
        result = attempts.verify(key, body.pin, token) if require_auth else 'ok'
        if result == 'limited':
            raise HTTPException(429, 'Too many PIN attempts; retry in five minutes', headers={'Retry-After': '300'})
        if result != 'ok':
            raise HTTPException(401, 'Incorrect access PIN')
        session = secrets.token_urlsafe(32)
        with auth_lock:
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
    @app.get("/api/v1/config")
    def get_config():
        return engine.config.public()

    @app.patch("/api/config")
    @app.patch("/api/v1/config")
    async def set_config(changes: dict):
        try:
            await asyncio.to_thread(engine.configure, changes)
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        return engine.config.public()

    @app.get("/api/devices")
    @app.get("/api/v1/devices")
    async def get_devices():
        try:
            return await asyncio.to_thread(input_inventory)
        except RuntimeError as exc:
            return {"devices": [], "default_input": None, "error": str(exc)}

    @app.get("/api/measurements")
    def measurements():
        return engine.snapshot()

    @app.post("/api/capture/{action}")
    @app.post("/api/v1/capture/{action}")
    async def capture(action: str):
        if action not in ("start", "stop"):
            raise HTTPException(404, "Unknown action")
        try:
            await asyncio.to_thread(engine.start if action == "start" else engine.stop)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        return engine.snapshot()["status"]

    @app.post("/api/baseline/calibrate")
    @app.post("/api/v1/baseline/calibrate")
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
    @app.get("/api/v1/events/export")
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
    @app.websocket("/ws/live")
    async def websocket(websocket: WebSocket):
        if not host_valid(websocket) or not origin_valid(websocket) or not authorized(websocket):
            await websocket.close(code=1008)
            return
        if engine.clients >= 32:
            await websocket.close(code=1013)
            return
        await websocket.accept()
        engine.clients += 1
        try:
            while True:
                if not authorized(websocket):
                    await websocket.close(code=1008)
                    break
                snapshot = engine.snapshot()
                snapshot["integrations"] = hub.snapshot(engine.config.argos_enabled, snapshot.get("timestamp"))
                snapshot['vision'] = vision.status()
                await asyncio.wait_for(websocket.send_json(snapshot), timeout=2)
                await asyncio.sleep(1 / engine.config.update_hz)
        except (TimeoutError, WebSocketDisconnect, RuntimeError):
            pass
        finally:
            engine.clients -= 1

    install_api(app, engine, hub, discovery, server_id, require_auth)
    from .vision_api import install_vision_api
    install_vision_api(app, vision)
    dashboard = Path(__file__).parent / "dashboard"
    app.mount("/", StaticFiles(directory=dashboard, html=True), name="dashboard")
    return app
