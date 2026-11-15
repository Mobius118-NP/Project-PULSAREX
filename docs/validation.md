# Validation — 15 November 2026

## v0.2.0 reliability pass

The expanded suite adds regression coverage for fault recovery, input switching while failed, native-worker timeout/termination, actual invalid-device worker startup without capture, lifecycle concurrency, stale measurements, calibration gaps, persistence failures, malformed requests and revoked-cookie replay. Browser checks verified that recovery/configuration controls remain enabled during an input fault, and that switching to simulation, pausing and resuming work without restarting the server. See [audit notes](audit-2026-11-15.md).

The user reported successful live capture with the previous revision. The new capture-process recovery path was tested with synthetic/fake inputs and an invalid native device; real unplug/replug behavior should still be checked with the user's microphone in a normal Windows session.

## Initial implementation checks

The synthetic suite covers frequency/level detection, harmonic grouping, silence, signed frequency shifts, competing-tone ambiguity, gradient continuity and saturation, calibration persistence, event thresholds/cooldown, disappearance, retention, synthetic broadband array bearing, validation and acquisition lifecycle.

API tests cover dashboard serving, measurements, capture controls, calibration, configuration validation, LAN token enforcement, browser cookies, bearer access, logout, cross-origin requests, host checks, WebSocket authentication/schema and processed-event CSV export.

Local HTTP and WebSocket startup was exercised and the live dashboard opened successfully in simulation mode. Simulation does not activate the microphone or play sound. Source data are synthetic; the UI's synthetic bearing is explicitly labelled.

Hardware limitation: the Intel microphone is enumerated by PortAudio, but opening streams in this managed development session failed through MME, DirectSound and WASAPI. Windows Audio services were running. Capture permission/device availability is not established by enumeration. Live capture must be tested from the user's own terminal with microphone access for desktop apps enabled. Real microphone-array accuracy and LAN operation across separate devices remain unvalidated.

The test client currently reports an upstream Starlette/httpx deprecation warning; test requests still execute. No microphone recordings are created by the test suite.
