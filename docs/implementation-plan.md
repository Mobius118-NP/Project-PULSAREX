# Implementation plan

1. Configuration and deterministic synthetic acquisition; finite, bounded measurements.
2. Windowed FFT, interpolated peaks, dBFS, flux, centroid and harmonic candidates.
3. Timed baseline calibration, deviation detection, cooldown and persistence.
4. Bounded SQLite event retention; export processed events only.
5. Local FastAPI server, authenticated LAN option, latest-frame WebSocket delivery.
6. Responsive canvas dashboard; smooth shift gradient; honest experimental direction states.
7. Synthetic DSP/API/security/streaming tests, browser review and launch verification.

Each implementation stage is validated before final delivery. Microphone operation and real-array accuracy require separate hardware validation.
