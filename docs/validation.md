# Validation

## Brutalist terminal palette — 18 November 2026

Applied the exact supplied palette to surfaces, text, borders, charts and status
controls; bundled IBM Plex Sans/Mono and their OFL notices for local serving.
Browser computed-style checks confirmed chassis `rgb(16,19,16)`, instrument panel
`rgb(9,12,9)`, divider `rgb(72,80,71)`, zero border radius, no panel box shadow and
no page background image. Both named fonts were loaded successfully. No browser
JavaScript errors were reported. At a 390 px viewport the archive's Clear archive
control remained inside the page, with no horizontal document overflow. Dashboard
script syntax and Ruff checks passed. The 122-test backend suite passed before the
subsequent presentation-only edits. Signed frequency-shift mapping is preserved.
Preview: [current terminal dashboard](terminal-preview.jpg).

## Six-digit PIN and archive cleanup — 18 November 2026

Full suite: **122 passed**, 25.52 seconds, one upstream Starlette/httpx deprecation
warning. Ruff passed; dashboard JavaScript syntax checks passed. Eight new tests
cover leading-zero PIN generation/validation, concurrent and global failed-guess
budgets, expiry, shared login/API/WebSocket limits, existing sessions during
lockout, rejection of old long credentials, archive/signature preservation,
monotonic IDs across clear/restart, queued-write ordering, authentication/explicit
confirmation/origin checks, detector reset and storage-failure reporting.

The source GUI generates exactly six ASCII digits with a cryptographically secure
random generator. PINs are not stored in preferences or included in URLs. Login
creates a separate random session cookie. Both HTTP bearer guesses and WebSocket
handshakes use the same five-per-client/thirty-per-server five-minute failure
budgets. Console operation accepts `PULSAR_PIN` (with a six-digit `PULSAR_TOKEN`
environment-variable alias). No new EXE was built.

Browser checks used a separate disposable, PIN-protected test server and synthetic
audio. A PIN containing a leading zero authenticated successfully. Event archive
displayed Clear archive and reached an empty state after clearing test records.
The user's actual event database and ARGOS catalogue were not modified by these
checks. See [PIN login](pin-login.jpg) and [archive control](archive-clear.jpg).

## PULSAREX 0.5.0 ARGOS integration — 18 November 2026

Follow-up: installed the official buffalo_l `w600k_r50.onnx` model locally and
verified the archive/model hashes; see [model evidence](argos-models.md). ONNX
Runtime returned a finite 512-component synthetic result. A separate real-model
smoke check computed a synthetic image embedding, explicitly enrolled it in a
disposable test catalogue, matched it and reloaded the persisted name. No real
person was enrolled or added to the user's catalogue. This establishes the model
and persistence path, not biometric accuracy.

Camera viewing and inline enrollment/catalogue controls now live under **ARGOS**.
Monitor retains the acoustic instruments and visual-vector overlay. Browser checks
confirmed live recognition startup, a detected face vector continuing on Monitor
while the camera view/enrollment controls were hidden, and no JavaScript errors.
At a 390 px viewport the ARGOS page had no horizontal overflow, and its enrollment
controls remained available. Camera capture was stopped before saving the ARGOS
page screenshots. [Monitor overlay](monitor-argos-overlay.jpg) and
[ARGOS menu](argos-menu.jpg) previews show the separated workspaces.
The six vision cases passed again; Ruff and all three dashboard script syntax
checks passed. The older observations adapter also moved to ARGOS.

Full PULSAR suite: **114 passed**, 65.89 seconds. Warnings were the existing upstream
Starlette/httpx deprecation and an unwritable old pytest cache directory; all tests
completed. Ruff and JavaScript syntax checks passed. Six new vision cases cover
78° projection/heading/wraparound, bounded stale-frame eviction, LAN authentication,
frame sequencing/stop, root/settings validation, separate WebSocket metadata and
worker processing of synthetic pixels with detector/recognizer doubles. Synthetic
identity tests do not use real biometric data or establish recognition accuracy.
Catalogue commands also reject missing identity/track selections and blank renames.

Physical camera 0 successfully opened and produced fresh frames at 640×480. The
background browser displayed live video through the combined server, no browser
script errors were reported, catalogue controls opened, and Stop camera released
capture. No camera images, audio recordings or new enrolled identities were saved.
The [combined dashboard preview](combined-dashboard.jpg) was captured after stopping
the camera, using synthetic audio. It shows the new viewing panel beside the PPI.

The original ARGOS test suite was also run: **20 passed, 1 failed**. Its existing
`test_catalogue_graphical_list_name_editor_and_association_controls` test hardcodes
desktop catalogue positions/callback assumptions that differ from the current
ARGOS layout. That standalone desktop test remains unresolved; ARGOS application
source was not changed. The new server catalogue is covered separately.

Dependencies were installed in the source launcher's full-Python `.venv-gui`.
ARGOS's missing YuNet weights were obtained with its existing OpenCV download helper.
At the initial integration check, ArcFace weights and enrolled templates were
absent; the weights have since been installed as described above. Real face-recognition
accuracy, calibrated FOV/heading accuracy, simultaneous hardware audio/video
performance, camera unplug/replug, prolonged memory stability and cross-device
LAN video/jitter performance remain unvalidated.
No new EXE was built; this integration is source-launcher only for now.

## PULSAREX 0.4.0 GUI launcher - 17 November 2026

Full suite: **108 passed**, one upstream Starlette/httpx deprecation warning,
34.30 seconds in an isolated full Windows Python environment with working Tcl/Tk.
Six new process-level tests verify Local/LAN settings, authentication enforcement,
no token persistence, occupied-port refusal, graceful shutdown/port release, startup
cancellation and restart. Python/Ruff checks passed. Native window layout was
visually inspected; the form includes scrolling for smaller displays. The interface
is separate from the server process and closes its server on exit.

The prior development runtime has Tcl DLLs but lacks compatible Tcl script assets;
the isolated `.venv-gui` uses the installed full Windows Python. Packaged artifacts
bundle their own Tcl/Tk and require no Python installation. Frozen process checks,
source/bundle comparisons and delivery evidence are recorded in
`release-evidence-0.4.0.json` after the final package validation. Cross-device LAN
reachability and clean-machine installation remain separate hardware/network checks.


## PULSAREX 0.3.1 two-microphone update - 17 November 2026

Full suite: **102 passed**, one upstream Starlette/httpx deprecation warning,
12.96 seconds. Added 21 test cases for known two-microphone bearings and mirror
candidates, rotated pair geometry, synchronization requirements, duplicate/inverted
mono rejection, invalid spacing/sampling, single-channel unavailability, stale
readouts, device-change verification reset and the paired WebSocket/history format.
The previous three-or-more-microphone and single-channel suites continue to pass.

The live direction route now accepts two synchronized channels; the polar display
shows both possible bearings and uncertainty sectors. Synthetic UI bearings remain
explicitly simulated and contain no invented measured stereo delay. Browser checks
and packaged-process validation are recorded in release-evidence-0.3.1.json.
The rebuilt executable passed the two-channel demo, baseline calibration, pause/resume and invalid-device recovery smoke test outside the virtual environment (26.735 s startup on this run). All 16 frozen Python modules and dashboard assets matched source. Browser rendering/settings checks passed with no console errors. No calibrated physical two-microphone capture was performed in this environment.
See [setup and physical assumptions](two-microphone-bearing.md).

## PULSAREX 0.3.0 — 17 November 2026

Final source suite: **81 passed**, one upstream Starlette/httpx deprecation warning,
17.81 seconds on this Windows host. Ruff checks, Python compilation and both dashboard
JavaScript syntax checks passed. Original audit suite: 61 passed before changes.
The first audit attempt hit a pre-existing Windows pytest temporary-folder ACL;
using a fresh workspace `.test-tmp` directory resolved that environment issue.

Tests added for robust outlier-resistant calibration; clipped time-based adaptation
and anomaly exclusion/freeze; named profiles/input compatibility; fan-plus-new-tone,
stopping and changing speed; low-frequency/broadband changes; stable UUID lifecycle;
duration, annotations/signatures; v1 API/authentication and WebSocket schema;
ARGOS separation; stereo duplicate/narrowband rejection; endpoint failover/identity
mismatch/LAN restoration; nonfinite payloads; request/rate bounds; and bounded slow
event storage. Tests use synthetic signals; no physical audio hardware is required.

The deterministic fan/noise holdout test observes 40 stable frames and 40 added-tone
frames: **0 false positives / 40**, **0 misses / 40** under those specific conditions.
It is not an estimate of field accuracy. Separate synthetic scenarios confirm fan
stopping and a 180 Hz fundamental shifting to 230 Hz. Original fan spectral peaks
remain present while the added 7.2 kHz tone is detected.

The final normal 600-frame offline pipeline benchmark measured **1.201 ms median** and
**3.803 ms p95**, compared with a 21.333 ms hop budget (48 kHz / 1024 samples).
These are host-specific synthetic measurements, not guaranteed laptop performance.
A separate allocation-traced run showed 10,048 bytes of second-half traced growth;
tracing raised timings above the hop budget. Traced peak allocation excludes objects
created before tracing, native libraries, interpreter and overall resident memory.
No overnight hardware stability/memory soak was performed.

The PyInstaller executable was built and smoke-tested with development Python
environment variables removed, a sanitized PATH and a different working directory.
The check covers static dashboard/API serving, automatic calibration, saved/frozen
baseline, pause/resume validity, invalid-device spawned-worker failure and recovery
to simulation. Initial measured startup: 17.031 seconds; folder size about 148 MB.
Final distribution verification results accompany the local release artifacts.
The packaged Python module code objects were compared against current source;
all module bytecode/constant comparisons matched, including the final event-gap and
frequency-range boundary corrections.
This is an independent packaged-process check on the development host, not a clean
Windows machine certification. Nuitka was not built or benchmarked.

Browser checks observed live synthetic instruments, full history bounded at 180
frames, freeze/save profile, event inspection/annotation and signature comparison,
and immediate stop clearing current readouts. At a 390 px viewport the document
width stayed within the viewport. Final browser error log was empty. Screenshot:
[dashboard preview](dashboard-preview.jpg). Interface and API checks do not establish
acoustic or direction accuracy.

Unvalidated: live microphone sensitivity/frequency response, real shared-clock
stereo/array calibration, cross-device LAN and mDNS discovery, real ARGOS transport,
public HTTPS deployment, clean-machine executable installation, and long-duration
hardware operation. Public serving and automatic known-state alert suppression
remain disabled/unimplemented. See [feature boundaries](features.md).

## Earlier validation — 15 November 2026

## v0.2.0 reliability pass

The expanded suite adds regression coverage for fault recovery, input switching while failed, native-worker timeout/termination, actual invalid-device worker startup without capture, lifecycle concurrency, stale measurements, calibration gaps, persistence failures, malformed requests and revoked-cookie replay. Browser checks verified that recovery/configuration controls remain enabled during an input fault, and that switching to simulation, pausing and resuming work without restarting the server. See [audit notes](audit-2026-11-15.md).

The user reported successful live capture with the previous revision. The new capture-process recovery path was tested with synthetic/fake inputs and an invalid native device; real unplug/replug behavior should still be checked with the user's microphone in a normal Windows session.

## Initial implementation checks

The synthetic suite covers frequency/level detection, harmonic grouping, silence, signed frequency shifts, competing-tone ambiguity, gradient continuity and saturation, calibration persistence, event thresholds/cooldown, disappearance, retention, synthetic broadband array bearing, validation and acquisition lifecycle.

API tests cover dashboard serving, measurements, capture controls, calibration, configuration validation, LAN token enforcement, browser cookies, bearer access, logout, cross-origin requests, host checks, WebSocket authentication/schema and processed-event CSV export.

Local HTTP and WebSocket startup was exercised and the live dashboard opened successfully in simulation mode. Simulation does not activate the microphone or play sound. Source data are synthetic; the UI's synthetic bearing is explicitly labelled.

Hardware limitation: the Intel microphone is enumerated by PortAudio, but opening streams in this managed development session failed through MME, DirectSound and WASAPI. Windows Audio services were running. Capture permission/device availability is not established by enumeration. Live capture must be tested from the user's own terminal with microphone access for desktop apps enabled. Real microphone-array accuracy and LAN operation across separate devices remain unvalidated.

The test client currently reports an upstream Starlette/httpx deprecation warning; test requests still execute. No microphone recordings are created by the test suite.
