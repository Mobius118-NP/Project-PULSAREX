# ARGOS + PULSAREX — 0.5.0

The source launcher now serves one dashboard with two workspaces. **Monitor** contains
PULSAREX's acoustic tools and bearing PPI, including the face-vector overlay.
**ARGOS** contains the camera viewing window, face enrollment/catalogue and advanced
external visual-adapter controls. Processing remains
local. The camera is off on server startup. No audio/video recording is added.

## Start on this computer

1. Double-click `Start-PULSAR.cmd` in the PULSAR project.
2. Choose Local only, or LAN (same Wi-Fi), then Start server and Open dashboard.
3. Open the **ARGOS** menu. In ARGOS / live camera, leave Camera index at 0 for the default webcam. Select
   another index if needed. Close the original ARGOS camera window if it owns the
   same device.
4. Set Camera heading to the camera optical axis in the acoustic display's coordinate
   system. Zero points up; angles increase clockwise. This is an operator-defined
   alignment, not a measured compass heading.
5. Click Start ARGOS camera. Face IDs and enrollment are enabled by default for
   consenting participants; uncheck the option for detection only. Use the adjacent
   Face enrollment & catalogue panel to select a visible track, enter a name and
   click Enroll track. Enrollment still requires explicit confirmation. Switch to
   Monitor to see the sound instruments and live face vectors; changing menus does
   not stop capture. Stop camera releases video capture; audio remains independently
   controlled. Stop server closes both workers.
6. In LAN mode, use the launcher's Copy LAN link and Copy PIN on a device on the
   same trusted network. Both video and identities require the existing authenticated
   dashboard session. HTTP is unencrypted; the existing private-network guidance applies.

This workspace has the vision dependencies installed in `.venv-gui`, which the
source launcher prefers. For a new setup, install a full Python 3.11+ with Tk,
run `Install-PULSAR.cmd`, and place the existing ARGOS checkout at `%USERPROFILE%\ARGOS`.
The equivalent dependency command is `python -m pip install -e ".[dev,vision]"`.
ARGOS code and its model weights are external local prerequisites, not copied into
the PULSAR package. Do not use the earlier EXE for these new features; repackaging is deferred.

## Detection and identity prerequisites

The worker uses ARGOS's `config/default.yaml`, YuNet detector, centroid tracker,
ArcFace recognizer and bounded embedding worker. The configured YuNet ONNX weights
must exist. The existing ARGOS setup helper can install its OpenCV YuNet model;
this integration does not download models during capture. YuNet was installed on
this host and camera 0 produced live frames during validation.

Face detection and vectors work without identity recognition. To display enrolled
IDs, supply the configured local ArcFace model (normally `models/w600k_r50.onnx`)
and enable face IDs before starting the camera. The existing
catalogue path is normally `data/face_templates.json`. A missing catalogue starts
empty; it does not create or enroll an identity automatically. Unknown or ambiguous
matches stay Unknown. Recognition scores are model similarities, not proof of identity.
The ArcFace weights are now installed on this host. Its real ONNX model passed a
finite 512-component output check on synthetic input. The catalogue starts empty;
no real participants were enrolled during validation, and real recognition accuracy
remains unvalidated. See [model provenance and license](argos-models.md).

Face catalogue exposes explicit enrollment, association with an existing ID, rename,
category editing and deletion using ARGOS's existing local catalogue methods.
Enrollment/association requires a currently visible track with a computed embedding.
Only enroll consenting participants. These explicit actions can modify the original
ARGOS catalogue; avoid running concurrent catalogue editors. No embeddings are sent
to the browser. Existing standalone ARGOS tools, including duplicate-template audit
and its desktop views, remain available in ARGOS; their native windows are not
embedded in the web dashboard. The original sequential stereo/ranging view is not
used: this integration deliberately provides direction only.

## Geometry and interpretation

The assumed horizontal FOV is **78 degrees**. For normalized face center `x`, the
rectilinear projection is:

`bearing = (heading + degrees(atan((2*x - 1) * tan(radians(39))))) % 360`

The left/right image edges therefore map to heading minus/plus 39 degrees. This
assumes an unmirrored, approximately rectilinear camera image. Lens distortion,
camera crop and an incorrect FOV or heading introduce error. No camera intrinsics
or compass calibration is inferred. The shared PPI's 000° label is a plotting
reference; north requires an externally aligned installation.

Signal-white visual rays and fixed-radius face markers show image-derived direction and
track/face ID. Radius never means distance. Olive/amber acoustic rays retain their
own uncertainty and, for two microphones, both unresolved mirror candidates.
Visible faces do not choose between those acoustic candidates. The application
does not claim that a visible person made a sound. Single-mic operation can show
camera rays while acoustic direction remains unavailable. Synthetic acoustic bearings
remain explicitly labelled when a live camera is enabled during audio simulation.

## Bounded smoothing and failure behavior

- Native camera/model calls run in a separate spawned process, independent of HTTP
  and audio. The parent can terminate a stuck worker when stopping.
- Capture uses a latest-frame queue of two, IPC uses three packets and the server
  retains eight JPEG packets. Native capture is requested at 640×480 / 30 fps;
  actual throughput depends on hardware. Detection runs at most 10 Hz, with at most
  32 visible faces and a four-job recognition queue. JPEG quality is 72.
- Each browser fetches at most 20 frames/sec with one request in flight and a
  2.5-second request timeout. Its decoded queue holds six frames; playback is capped
  at 30 redraws/sec. Obsolete bitmaps are explicitly closed.
- The adjustable 0–300 ms arrival buffer defaults to 160 ms. It absorbs brief jitter
  by playing buffered real frames. It cannot reconstruct frames lost before capture
  or guarantee smooth output over a long outage. The final frame is held with a
  STALE / HOLDING LAST FRAME label when needed; no fabricated motion is generated.
- Frame and detection ages are checked separately. Face boxes/IDs/vectors expire
  after one second. Client/server wall-clock agreement is not required for the
  browser's freshness calculations. The video frame and its associated metadata
  travel together, so overlays correspond to the buffered video, not the latest
  independent acoustic timestamp.
- Stop camera clears cached packets, decoded images and the viewing canvas. A
  disconnect or model failure produces a visible status; Stop then Start retries.
  Startup/stalls time out after 30 seconds. No fallback video is invented.

## API and privacy

`GET /api/v1/vision` reports status; `POST /start` and `POST /stop` beneath that path
control the local worker. `GET /frame?after=N` returns the newest JPEG plus its
timestamp, sequence and face metadata, or 204. `GET /catalogue` returns catalogue
metadata; `POST /catalogue` queues an explicit action and returns 202. Queuing is
not completion: read `command_status`. The WebSocket includes a separate `vision`
status object without JPEG images or biometric embeddings.

All routes use the existing authentication, same-origin controls and `no-store`
headers. For security, the API can load only `%USERPROFILE%\ARGOS`; a LAN client
cannot select an arbitrary executable Python project path. Camera frames and
recognized labels are visible to authorized dashboard clients when the operator
starts capture. Do not grant the shared LAN PIN to someone who should not see them.
The older `/integrations` visual-observation API remains separate and continues
rejecting identity payloads; it cannot inject face IDs into this trusted local path.
