# PULSAR Mk. II

LAN-based acoustic spectral mapping and environmental change detection.

This repository currently contains the project setup and agreed design requirements. The application has not been implemented yet.

## Planned architecture

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
