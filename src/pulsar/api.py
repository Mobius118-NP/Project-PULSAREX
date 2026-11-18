"""Versioned routes; server middleware authenticates all /api paths."""
import asyncio
import socket
import sqlite3
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from fastapi import HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .integrations import VisualObservation
from .network import lan_addresses


class ProfileRequest(BaseModel):
    name: str = Field(default="default", min_length=1, max_length=48)


class Annotation(BaseModel):
    annotation: str = Field(max_length=2000)


class SignatureRequest(BaseModel):
    event_id: int = Field(ge=1)
    label: str = Field(min_length=1, max_length=120)


class ClearEventsRequest(BaseModel):
    confirm: Literal[True]


class ExternalEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    schema_version: int = Field(default=1, ge=1, le=1)
    timestamp: datetime
    sensor_id: str = Field(min_length=1, max_length=96)
    category: Literal["UNKNOWN_ANOMALY", "spectral change", "tonal change", "broadband transient"] = "UNKNOWN_ANOMALY"
    band_hz: list[float] = Field(default_factory=list, max_length=2)
    change_db: float = Field(ge=0, le=280)
    duration_seconds: float = Field(ge=0, le=86400)
    score: float = Field(ge=0, le=1)

    @field_validator("timestamp")
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None:
            raise ValueError("Timezone-aware UTC timestamps required")
        return value.astimezone(UTC)

    @field_validator("band_hz")
    @classmethod
    def ordered(cls, values):
        if values and (len(values) != 2 or not 0 <= values[0] <= values[1] <= 96000):
            raise ValueError("Use an ordered [lower, upper] frequency range")
        return values


def install_api(app, engine, hub, discovery, server_id, require_auth):
    @app.get("/api/v1/status")
    def status():
        frame = engine.snapshot()
        return {"schema_version": 1, "server_id": server_id, "status": frame["status"],
                "measurement_valid": frame["measurement_valid"], "hostname": socket.gethostname(),
                "lan_addresses": lan_addresses(), "host": engine.config.host, "port": engine.config.port,
                "authentication_required": require_auth, "mdns": discovery.status,
                "public_access": "disabled", "connected_clients": engine.clients}

    @app.get("/api/v1/spectrum")
    def spectrum():
        return engine.snapshot()

    @app.get("/api/v1/baseline")
    def baseline():
        return engine.snapshot()["baseline"]

    @app.get("/api/v1/baseline/profiles")
    def profiles():
        with engine.lock:
            return {"profiles": engine.profiles.names(), "active": engine.profile_id,
                    "matching_known_state": engine.known_state,
                    "activation": "operator selected; similarity does not suppress alerts"}

    @app.post("/api/v1/baseline/{action}")
    def profile(action: str, body: ProfileRequest | None = None):
        try:
            return engine.profile(action, body.name if body else "default")
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(503, "Baseline storage unavailable") from exc

    @app.get("/api/v1/events")
    def events(limit: int = Query(100, ge=1, le=5000), category: str | None = None,
               band: str | None = None, since: datetime | None = None, until: datetime | None = None):
        selected = engine.store.recent(5000, category)
        def timestamp(event):
            try:
                return datetime.fromisoformat(event["timestamp"].replace('Z', '+00:00')).timestamp()
            except (KeyError, TypeError, ValueError):
                return 0
        if (since and since.tzinfo is None) or (until and until.tzinfo is None):
            raise HTTPException(422, "Filter times must include a timezone")
        filtered = [e for e in selected if (band is None or e.get('frequency_band') == band)
                    and (since is None or timestamp(e) >= since.timestamp())
                    and (until is None or timestamp(e) <= until.timestamp())]
        return {"schema_version": 1, "events": filtered[:limit], "total": engine.store.count(),
                "filtered_total": len(filtered)}

    @app.post("/api/v1/events", status_code=201)
    def ingest(event: ExternalEvent):
        data = event.model_dump(mode="json")
        data.update(event_id=str(uuid4()), source="external", state="submitted",
                    uncertainty="External observation; not a local microphone measurement")
        return engine.store.add(data)

    @app.delete('/api/events')
    @app.delete('/api/v1/events')
    async def clear_events(body: ClearEventsRequest):
        try:
            deleted = await asyncio.to_thread(engine.clear_events)
        except (RuntimeError, OSError, sqlite3.Error) as exc:
            raise HTTPException(503, 'Could not finish clearing the archive; refresh and retry shortly') from exc
        return {'deleted': deleted, 'scope': 'all events and event annotations', 'signatures_retained': True}

    @app.get("/api/v1/events/{event_id}")
    def detail(event_id: int):
        try:
            return {**engine.store.get(event_id), "signature_comparisons": engine.store.compare(event_id)}
        except KeyError as exc:
            raise HTTPException(404, "Event not found") from exc

    @app.patch("/api/v1/events/{event_id}")
    def annotate(event_id: int, body: Annotation):
        try:
            return engine.store.annotate(event_id, body.annotation)
        except KeyError as exc:
            raise HTTPException(404, "Event not found") from exc

    @app.get("/api/v1/signatures")
    def signatures():
        return {"signatures": engine.store.signatures(), "meaning": "Human-reviewed feature similarity, not identity"}

    @app.post("/api/v1/signatures", status_code=201)
    def signature(body: SignatureRequest):
        try:
            return engine.store.save_signature(body.event_id, body.label)
        except KeyError as exc:
            raise HTTPException(404, "Event not found") from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/v1/integrations")
    def integrations():
        return {"argos": hub.snapshot(engine.config.argos_enabled),
                "vibration": {"mode": "independent Python sensor adapter", "raw_audio": False}}

    @app.post("/api/v1/integrations/argos", status_code=201)
    def argos(body: VisualObservation):
        if not engine.config.argos_enabled:
            raise HTTPException(409, "ARGOS adapter is disabled")
        return hub.add_visual(body)

    @app.get("/api/v1/openapi.json")
    def schema():
        return app.openapi()

    @app.get("/api/v1/docs", response_class=HTMLResponse, include_in_schema=False)
    def docs():
        return '<!doctype html><html lang="en"><meta charset="utf-8"><title>PULSAREX API</title><link rel="stylesheet" href="/style.css"><main><h1>PULSAREX API v1</h1><p>Six-digit PIN as a Bearer credential or authenticated same-origin session required in LAN mode. POST, PATCH and DELETE are controls. All units are relative digital measurements.</p><p><a href="/api/v1/openapi.json">Download OpenAPI schema</a> · <a href="/">Dashboard</a></p><pre id="api-schema">Loading local schema…</pre></main><script src="/api-docs.js"></script></html>'
