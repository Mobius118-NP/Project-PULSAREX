# Project PULSAREX

**PULSAR Mk. II — passive acoustic analysis and environmental monitoring.**

LAN-based acoustic spectral mapping and environmental change detection.

The application includes a responsive local dashboard, microphone and synthetic acquisition, FFT/STFT spectrum and spectrogram, harmonic candidates, baseline calibration, processed-event history/CSV export, and experimental shift and array-direction displays.

**PULSAREX 0.5.0** combines the local ARGOS camera with this server and dashboard:
live video, 78° horizontal field of view, direction-only face vectors and optional
enrolled face IDs on the acoustic PPI. The **ARGOS** menu contains camera viewing
and enrollment; **Monitor** keeps the sound instruments and face-vector overlay.
A bounded playback buffer absorbs
short arrival gaps; stale video is labelled and old face vectors expire. Camera
capture starts only when requested. See [ARGOS setup and limitations](docs/argos-integration.md).

The application also includes robust median/MAD background learning, optional clipped EWMA
adaptation, detection on full FFT bins, multiple environmental profiles, event
lifecycle/review, compact signature memory, versioned APIs, optional ARGOS/FOV and
stereo-delay adapters, discovery and a Windows executable build. Existing capture,
recovery, dashboard identity and continuous shift colors are preserved.

See the [feature matrix and limitations](docs/features.md),
[acoustic model](docs/acoustic-model.md), [API](docs/api-v1.md),
[networking](docs/networking.md) and [Windows packaging](docs/packaging.md).

## Start on Windows

Double-click **PULSAREX.exe** from `dist/onefile` for the bundled Windows x64 app.
Python, Tcl/Tk, the dashboard, the ARGOS runtime and both models are included. For
source development, use **Start-PULSAR.cmd** and a local ARGOS checkout. The bundled
InsightFace model is for non-commercial research. [Windows build details](docs/packaging.md).

The native GUI opens without a terminal. Choose **LAN (same Wi-Fi)**, keep or generate
a six-digit PIN, then click **Start server**. Use **Copy LAN link** on another device
and **Copy PIN** for its login. Choose **Local only** to keep access on this computer.
**Stop server** or closing the launcher stops capture and the server.

The GUI includes source/port selection, optional TOML configuration, masked PIN,
browser opening and adapter-aware links. Preferences persist; the PIN is never
saved. See [GUI launcher instructions](docs/gui-launcher.md).


For a source checkout, run `Install-PULSAR.cmd` once, then double-click `Start-PULSAR.cmd` to open the GUI. A full Python 3.11+ installation with Tcl/Tk is required. The following commands retain console operation; Ctrl+C stops that console server.

From PowerShell in this folder:

```powershell
py -3 -m venv .venv
& ".\.venv\Scripts\python.exe" -m pip install -e ".[dev,vision]"
& ".\.venv\Scripts\python.exe" -m pulsar.main
```

For a fresh clone, first run `git clone <your-repository-url> pulsar-mk2` and `cd pulsar-mk2`. Use the repository URL for your checkout.

Default mode is **simulation**: a harmonic tone, slow frequency sweep, and periodic broadband event. It generates data without playing sound or using the microphone. Simulated bearing data are explicitly labelled and independent of the synthetic signal.

Camera and audio controls are independent. Starting the camera does not replace
synthetic audio with a live microphone. For a real acoustic bearing, configure a
suitable synchronized two-channel input and measured geometry. With one microphone,
visual vectors remain available while measured acoustic direction is unavailable.

## Live microphone

Choose **Configuration → Live microphone**, select an input and apply. Windows devices are labelled with their backend and native sample rate. Selecting an input sets its native rate, including the automatic WASAPI input. Pause acquisition stops the input worker; an unresponsive native driver is terminated. Nothing records raw audio.

```powershell
& ".\.venv\Scripts\python.exe" -m pulsar.main --list-devices
& ".\.venv\Scripts\python.exe" -m pulsar.main --source microphone --device 14
```

The device ID above is an example; use your own device list. Changes in the dashboard are session-only. For repeatable startup settings, copy `config.example.toml` to `config.toml`, edit it, and launch with `--config config.toml`.

If streams fail with MME error 1, DirectSound error or Invalid device:

- Check Windows Settings → Microphone: microphone access and access for desktop apps must be enabled.
- Select the working input's WASAPI entry and native rate, and check hardware mute.
- Close any app holding the microphone exclusively.
- Launch from your own PowerShell or `Start-PULSAR.cmd`; a restricted development process may see devices but fail to capture them.
- Restart PULSAR after changing audio hardware; cached device IDs can become stale.

The application retries input failures every three seconds and shows an explicit error. It never silently substitutes simulated data for a failed microphone.

During an input error, the **INPUT RECOVERY** panel stays available. Use **Refresh inputs**, **Retry current**, or **Use selected input** to recover without restarting the server. Input discovery and browser requests have separate failure states, so an unavailable input list does not disable the other controls. The driver runs in an isolated process with a six-second startup timeout. Switching devices clears previous array geometry unless you explicitly configure it for the new input.

The interface uses an olive/amber instrument layout with explicit ACQUIRING, HOLD, INPUT FAULT and LINK LOST states. The Doppler/spectrum-shift indicator keeps its continuous blue/violet → green → red convention.

The current [brutalist terminal theme](docs/terminal-theme.md) uses the specified
chassis/instrument blacks, olive, amber, signal white and fault red. Surfaces are
flat with square corners and no glow or shadows. IBM Plex Sans and IBM Plex Mono
are bundled locally for offline dashboard use.

## Architecture

- Python 3.11+: acquisition, DSP, event processing and SQLite persistence.
- NumPy/SciPy and sounddevice for spectral analysis and microphone input.
- FastAPI/Uvicorn and WebSockets for processed measurements.
- HTML/CSS/JavaScript dashboard for spectrum, spectrogram, baseline, events and experimental direction/shift displays.
- Synthetic demonstration mode and hardware-independent tests.

## Frequency-shift indicator

Use a continuous colour gradient: blue/violet for negative frequency shift, green around zero, and red for positive frequency shift. Intermediate values must blend continuously; do not switch between rigid colour categories.

See [the indicator requirements](docs/frequency-shift-indicator.md).

## Desktop shortcut

Double-click `Create-Desktop-Shortcut.cmd` to place a folder shortcut on your Windows Desktop. The installer uses this repository's current location and does not overwrite an existing shortcut.

## Implementation order

1. Configuration, synthetic signal generation and tests.
2. Microphone capture, FFT/STFT and spectral visualization.
3. Harmonic grouping and adaptive environmental baseline.
4. Event persistence and history.
5. Authenticated LAN dashboard and WebSockets.
6. Experimental direction and frequency-shift visualization.
7. Integration and performance validation.

Single-channel input supports spectral analysis. Direction estimates require suitable synchronized, calibrated microphone-array hardware. Unknown-source pitch variation is a spectral change, not confirmed Doppler motion.

## Baseline and event history

Calibrate a representative normal interval, then compare the spectrum against that profile. Optional slow adaptation excludes significant deviations. Matching calibrations survive restart. Events contain neutral observations and heuristic scores. Duration is elapsed deviation time while active and observed total duration when completed. CSV export contains processed measurements only. Retention is bounded to 5,000 events.

Initialization now starts calibration automatically unless `auto_calibrate = false`.
Leave normal fans, HVAC and other persistent background running while learning.
Nothing removes that background from the original spectrum. A new tone can trigger
an anomaly while the fan remains visible. The per-bin median/MAD model requires both
the dB threshold and robust variation threshold to be exceeded. Optional adaptation
changes the center slowly; MAD remains fixed until recalibration. Freeze prevents
adaptation, while manual reset starts a new calibration.

Save descriptive environmental states in **Environmental profiles & anomaly evidence**.
Load a reviewed profile when changing operating states. Similarity suggestions never
silently dismiss an anomaly. Calibration statistics from 0.2.0 are left intact but
require recalibration for the new FFT-bin model. Existing event history is preserved.

Click an event to inspect compact current/baseline evidence, add an annotation, and
save a reviewed signature. Signature distances assist review; they do not identify
the physical source. Active events update one record at cooldown intervals, complete
when the deviation ends, and are marked interrupted when capture stops. Completed
durations refer to observed acoustic deviations. A continuously changing demo can
remain one persistent spectral event rather than many independent sounds.

## Experimental measurements

Harmonic groups and temporal consistency are heuristic; they do not confirm source identity. The frequency-shift panel compares a detected tone with a known reference and marks similar competing tones ambiguous. It does not infer motion or velocity from arbitrary pitch changes. Its gradient is continuous with configurable neutral tolerance and colour saturation; numerical measurements remain unfiltered.

Two microphones on one synchronized input now provide two possible acoustic bearings, shown on the polar map with uncertainty and time-delay information. Set channels to 2, verify the shared-clock input, and configure spacing/orientation in Configuration. Front/back remains unresolved. Three or more non-collinear microphones can still use the planar-array estimator. See [two-microphone setup](docs/two-microphone-bearing.md). Confidence and uncertainty are heuristic, not calibrated probabilities.

## LAN access

The launcher provides **Generate PIN**, **Show PIN** and **Copy PIN**. PINs contain
exactly six digits, including any leading zeroes. They stay in memory and are not
saved with preferences. Browser login exchanges the PIN for a random session cookie.
Failed guesses are limited across login, API and WebSocket access; see
[networking](docs/networking.md). Older long access tokens are no longer accepted.

Loopback is the default. Explicit non-loopback binding requires an access PIN of exactly six digits:

```powershell
$env:PULSAR_PIN = Read-Host "Enter a six-digit access PIN"
& ".\.venv\Scripts\python.exe" -m pulsar.main --host 0.0.0.0
```

The server lists candidate LAN addresses. Open the host's address on an authorized device on the same network, for example `http://192.168.1.20:8765`, and enter the PIN. Browser sessions use HttpOnly/SameSite cookies; API clients can use `Authorization: Bearer ...`. Restarting the server invalidates browser sessions. Access includes capture/configuration controls.

Use a trusted private network. Plain HTTP is unencrypted; use an HTTPS reverse proxy when confidentiality is required. No router port forwarding, firewall changes, cloud service or external account is configured automatically. Do not expose the server publicly.

## Clear event history

Open **Event archive → Clear archive** and confirm. This removes all saved acoustic
events and their annotations. Saved signatures, baseline profiles and ARGOS face
identities remain available. Export CSV first if you want a copy. New detections
continue to populate the archive while acquisition is running. Clearing also drains
older queued writes so they cannot restore deleted records.

## Validation and limitations

```powershell
& ".\.venv\Scripts\python.exe" -m pytest -q
& ".\.venv\Scripts\python.exe" -m ruff check src tests
```

The synthetic tests cover spectral measurements, harmonics, signed shifts, gradient continuity, baselines, events/cooldown, bounded retention, simulated array bearing, lifecycle, REST controls, authentication, origin checks and WebSocket schema. Hardware accuracy and operation across separate LAN devices need separate validation. See [validation notes](docs/validation.md) and [architecture](docs/architecture.md).

If an old Windows pytest temporary folder has restrictive permissions, use:

```powershell
New-Item -ItemType Directory -Force .test-tmp | Out-Null
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp .test-tmp/run-unique
```

Choose a new run directory each time. Additional hardware-independent experiments:

```powershell
& .\.venv\Scripts\python.exe examples/profile_pipeline.py --frames 600
& .\.venv\Scripts\python.exe examples/profile_pipeline.py --frames 200 --trace
& .\.venv\Scripts\python.exe examples/multiresolution.py
```

Timing under allocation tracing includes tracing overhead; do not compare it directly
with the real-time hop budget. The GitHub workflow tests Python 3.11/3.12 on Linux
and Windows and builds/smoke-tests the Windows package when run on GitHub.

## Standalone Windows application

Build with `Build-PULSAREX.cmd`. The output is `dist/onefile/PULSAREX.exe`.
Copy this file to the Windows x64 host, double-click it, choose Local or LAN and
click **Start server**. The executable serves HTTP with its bundled Python runtime.
Packaged data default to `%LOCALAPPDATA%\PULSAREX`; `--data-dir` or external TOML
overrides it. Source launches retain the `data/` default. Browser changes are runtime
settings; put desired restart settings in external TOML:

```powershell
Copy-Item config.example.toml config.toml
& .\.venv\Scripts\python.exe -m pulsar.main --config config.toml --open-browser
```

For LAN, set `PULSAR_PIN`, then add `--host 0.0.0.0`; enter the host's LAN address
on another authorized device. Use its actual LAN IP, not 0.0.0.0 or the client's
127.0.0.1. Optional discovery needs `.[discovery]` and `mdns_enabled = true`.
Direct-IP access remains available when mDNS fails. Public internet serving stays
disabled; the HTTPS fallback utility is for independently secured integration clients.

## Repository map

```text
src/pulsar/audio.py          Bounded acquisition and isolated native driver process
src/pulsar/dsp.py            Windowed analysis and experimental array/shift measurements
src/pulsar/baseline.py       Robust background statistics and reviewed profiles
src/pulsar/events.py         Baseline-relative lifecycle and neutral characterization
src/pulsar/storage.py        SQLite events, annotations and signature memory
src/pulsar/engine.py         Capture/DSP coordination and bounded live snapshots
src/pulsar/server.py         Authentication, REST/WebSocket transport and local assets
src/pulsar/api.py            Versioned review, profile and integration endpoints
src/pulsar/integrations.py   Independent ARGOS evidence and external vibration adapter
src/pulsar/network.py        Optional discovery and endpoint recovery
src/pulsar/dashboard/        Self-contained responsive browser instruments
tests/                      Hardware-independent regression and synthetic tests
examples/                   Experiments, benchmark and frozen-server smoke test
packaging/                  Multiprocessing-safe executable entry point
```

MIT licensed. No GitHub publication is required for local operation.

Digital levels are dBFS, not calibrated SPL. No physical-object classification, source identity, distance estimation or motion confirmation is implemented. The spectrogram holds at most 180 frames; shift and bearing histories are bounded. The `data/` folder stores event/baseline statistics and is ignored by Git. Use microphones where you are authorized to capture sound.
