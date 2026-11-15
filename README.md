# PULSAR Mk. II

LAN-based acoustic spectral mapping and environmental change detection.

The application includes a responsive local dashboard, microphone and synthetic acquisition, FFT/STFT spectrum and spectrogram, harmonic candidates, baseline calibration, processed-event history/CSV export, and experimental shift and array-direction displays.

## Start on Windows

Run `Install-PULSAR.cmd` once, then double-click `Start-PULSAR.cmd`. Python 3.11+ is required. Open **http://127.0.0.1:8765** and keep the terminal open. Ctrl+C stops the server.

From PowerShell in this folder:

```powershell
py -3 -m venv .venv
& ".\.venv\Scripts\python.exe" -m pip install -e ".[dev]"
& ".\.venv\Scripts\python.exe" -m pulsar.main
```

For a fresh clone, first run `git clone <your-repository-url> pulsar-mk2` and `cd pulsar-mk2`. This local repository has no remote configured yet.

Default mode is **simulation**: a harmonic tone, slow frequency sweep, and periodic broadband event. It generates data without playing sound or using the microphone. Simulated bearing data are explicitly labelled and independent of the synthetic signal.

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

Calibrate a representative quiet interval, then compare the spectrum against that profile. Optional slow adaptation excludes significant deviations. Matching calibrations survive restart. Events contain neutral observations and heuristic scores, not identified objects. Duration is elapsed deviation time when an event is emitted. CSV export contains processed measurements only. Retention is bounded to 5,000 events.

## Experimental measurements

Harmonic groups and temporal consistency are heuristic; they do not confirm source identity. The frequency-shift panel compares a detected tone with a known reference and marks similar competing tones ambiguous. It does not infer motion or velocity from arbitrary pitch changes. Its gradient is continuous with configurable neutral tolerance and colour saturation; numerical measurements remain unfiltered.

Live bearing requires at least three non-collinear microphones on a synchronized input device with measured geometry in TOML. GCC-PHAT/far-field estimates are experimental and may be ambiguous for narrowband tones and reflections. Confidence and uncertainty are heuristic, not calibrated probabilities.

## LAN access

Loopback is the default. Explicit non-loopback binding requires an access token of at least 16 characters:

```powershell
$env:PULSAR_TOKEN = Read-Host "Enter a long random access token"
& ".\.venv\Scripts\python.exe" -m pulsar.main --host 0.0.0.0
```

The server lists candidate LAN addresses. Open the host's address on an authorized device on the same network, for example `http://192.168.1.20:8765`, and enter the token. Browser sessions use HttpOnly/SameSite cookies; API clients can use `Authorization: Bearer ...`. Restarting the server invalidates browser sessions. Access includes capture/configuration controls.

Use a trusted private network. Plain HTTP is unencrypted; use an HTTPS reverse proxy when confidentiality is required. No router port forwarding, firewall changes, cloud service or external account is configured automatically. Do not expose the server publicly.

## Validation and limitations

```powershell
& ".\.venv\Scripts\python.exe" -m pytest -q
& ".\.venv\Scripts\python.exe" -m ruff check src tests
```

The synthetic tests cover spectral measurements, harmonics, signed shifts, gradient continuity, baselines, events/cooldown, bounded retention, simulated array bearing, lifecycle, REST controls, authentication, origin checks and WebSocket schema. Hardware accuracy and operation across separate LAN devices need separate validation. See [validation notes](docs/validation.md) and [architecture](docs/architecture.md).

Digital levels are dBFS, not calibrated SPL. No physical-object classification, source identity, distance estimation or motion confirmation is implemented. The spectrogram holds at most 180 frames; shift and bearing histories are bounded. The `data/` folder stores event/baseline statistics and is ignored by Git. Use microphones where you are authorized to capture sound.
