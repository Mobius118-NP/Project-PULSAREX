# Local API v1 and integrations

Interactive endpoint index: `/api/v1/docs` (local assets only).
Machine-readable FastAPI OpenAPI: `/api/v1/openapi.json`.
LAN requests require `Authorization: Bearer <six-digit-PIN>` or an authenticated
same-origin browser cookie. The PIN grants control access. Do not embed it in
URLs or commit it. Browser login uses `POST /api/login` with JSON `{"pin":"......"}`
(replace the dots with six ASCII digits, keeping leading zeroes). The legacy JSON
field `token` accepts the same six-digit string; long tokens are no longer accepted.
Session status remains `/api/session`; legacy routes and `/ws` remain available.

| Method | Endpoint | Result |
|---|---|---|
| GET | `/api/v1/status` | Pinned server ID, input/processing status, host/LAN/port, clients, discovery |
| GET | `/api/v1/spectrum` | Latest processed snapshot and validity flag |
| GET/PATCH | `/api/v1/config` | Validated runtime settings; host/port require restart/TOML |
| GET | `/api/v1/devices` | Input inventory; no capture starts |
| POST | `/api/v1/capture/start`, `/stop` | Capture lifecycle |
| GET | `/api/v1/baseline` | Display baseline and calibration state |
| POST | `/api/v1/baseline/calibrate`, `/reset` | Learn representative current environment |
| POST | `/api/v1/baseline/freeze`, `/unfreeze` | Suspend/resume optional adaptation |
| GET | `/api/v1/baseline/profiles` | Saved names, active and matching state |
| POST | `/api/v1/baseline/save`, `/load` | JSON `{"name":"fan-operating"}` |
| GET | `/api/v1/events` | Bounded events; `limit`, `category`, `band`, `since`, `until` |
| POST | `/api/v1/events` | Validated external neutral observation; labelled external |
| DELETE | `/api/v1/events` | JSON `{"confirm":true}` clears all events/annotations; returns deleted count. Legacy alias `/api/events`. |
| GET/PATCH | `/api/v1/events/{id}` | Detail/comparison or JSON `{"annotation":"reviewed"}` |
| GET | `/api/v1/events/export` | Processed legacy-compatible CSV |
| GET/POST | `/api/v1/signatures` | Reviewed signatures; POST `{"event_id":1,"label":"description"}` |
| GET | `/api/v1/integrations` | Separate ARGOS evidence and status |
| POST | `/api/v1/integrations/argos` | Optional versioned visual observation |
| WS | `/ws/live` | `type: measurement`, `schema_version: 1`, sequence, stream ID, validity, processed features |

WebSocket authentication uses the same cookie or Authorization header; no tokens
in query strings. Data are bounded latest snapshots, not a lossless event stream.
Poll `/events` to recover missed notifications. Slow writes time out in two seconds;
clients reconnect and reset time history when stream ID changes. No raw samples are
transmitted. Maximum 32 WebSocket clients; main server caps 64 concurrent requests.
Control bodies are capped at 64 KiB and writes at 120/minute per client address.
Failed PIN guesses share one atomic budget across login, HTTP bearer requests and
WebSocket handshakes: five failures per client address and thirty across the server
per five minutes. Further guesses are rejected until the window expires. Existing
random browser sessions remain usable during lockout. This is a LAN perimeter,
not a reviewed public service.

Archive clearing follows queued older event writes, resets the active detector
lifecycle and retains baseline profiles, independent reviewed signatures and ARGOS
identities. New detections continue to be recorded. Event row IDs are not reused
after clearing, including across restarts. The dashboard asks for confirmation;
the API also requires `confirm:true`. A missing/false confirmation returns 422;
storage failure or a busy writer returns 503. Clearing is not secure disk erasure
and does not shrink the SQLite database file.

External event example (timezone required):

```json
{"schema_version":1,"timestamp":"2026-11-17T12:00:00Z","sensor_id":"external-01",
 "category":"UNKNOWN_ANOMALY","band_hz":[100,300],"change_db":15,
 "duration_seconds":0.4,"score":0.6}
```

ARGOS example (current timestamp within 60 seconds, synchronized UTC clocks):

```json
{"schema_version":1,"observation_id":"argos-001","timestamp":"2026-11-17T12:00:00Z",
 "camera_id":"camera-01","fov_center_deg":80,"fov_width_deg":60,
 "clock_uncertainty_ms":30,"description":"Independent visual observation"}
```

Enable `argos_enabled` explicitly. Identity fields are rejected. Camera FOV sectors
use signal-white dashed outlines on the shared polar visualization, independently from
olive acoustic bearings. Observation history is bounded at 256 and expires visually
after 60 seconds. Time association tolerance is the reported clock uncertainty plus
100 ms acoustic allowance; association is never causal attribution. Actual ARGOS
compatibility and clock alignment need end-to-end validation with that application.
The Python `vibration_features` adapter analyzes external sensor values separately;
it does not turn vibration units into acoustic levels.

Event signature comparison uses normalized compact spectral/aggregate vectors and
Euclidean distance. Lower means closer features, not confirmed identity. Library
limit is 256 reviewed entries. Legacy events lacking features cannot be enrolled.
The current timeline spaces observations by order and encodes score by height;
timestamps and exact durations are available in event details.

Two-microphone snapshots use `direction.mode = "two_microphone"`, `bearing_deg = null`, `possible_bearings_deg = [angle1,angle2]`, `uncertainty_deg`, `delay_seconds`, `confidence` and explicit ambiguity. Check validity and availability before using direction or stereo data. Simulated pairs carry `simulated = true` and no measured delay. Configuration adds `stereo_axis_deg` alongside spacing/synchronization.
