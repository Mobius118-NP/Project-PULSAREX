# Architecture

`audio.py` acquires float32 blocks from a local microphone or deterministic synthetic source. The PortAudio callback copies to a bounded eight-block queue and counts overruns. Native microphone calls run in a separate spawned process. A second bounded queue relays samples to the DSP worker; no DSP, disk or network work occurs inside the callback. Startup is cancellable and times out after six seconds. A hung driver process is terminated on stop, keeping the server responsive. Windows automatic input selection prefers the system WASAPI input; the inventory reports its actual native rate.

`dsp.py` applies a Hann window and FFT to a sliding frame, estimates peak frequencies, amplitude-normalized dBFS, spectral flux, amplitude-weighted centroid and relative noise floor. Log bins preserve local maxima. Sample rate and FFT size determine actual resolution; interpolated peak readouts do not add physical resolution.

Harmonic grouping is optional and heuristic. Frequency-shift estimates require a significant peak in the configured reference window. Competing similarly strong tones produce an ambiguous state. The continuous colour ramp has a green neutral plateau and continuous joins at its boundaries. Numerical measurements are not smoothed.

`baseline.py` uses online mean/variance during timed calibration. Quiet-frame adaptation is slow; significant deviations are excluded. Statistics are written atomically and checked against source/spectral settings before reuse.

`storage.py` detects positive and negative spectral deviations, applies a cooldown and stores observations in SQLite with WAL and locking. Retention is bounded to 5,000 rows. Duration is elapsed deviation time at emission, not a completed-event duration. Scores are heuristics, not classification probabilities.

`engine.py` owns acquisition, the sliding window, latest frame and bounded shift/bearing histories. Analysis runs at the hop cadence. Dashboard snapshots publish at an independent update rate. Slow browsers receive the newest snapshot rather than a queue. WebSocket writes time out after two seconds.

Control operations are serialized separately from snapshot locking, so stopping a worker never holds the lock the worker needs to finish. Threshold/reference controls update in place; source/format changes restart acquisition. New streams have unique IDs. Sequence discontinuities, overruns and reconnects clear the rolling FFT window and temporal associations. Missing, stopped or stale data invalidate current direction/shift readouts. Calibration counts contiguous acquired intervals rather than time spent disconnected. Baseline write failures are warnings rather than fatal acquisition errors, and adapted profiles are saved periodically and on stop.

`server.py` exposes REST controls and WebSockets. Loopback is the default; LAN binding requires a token. Same-origin checks protect browser controls and sockets. Dashboard scripts and charts are served locally with no CDN or telemetry.

`dashboard/` provides responsive canvas instruments, controls, event history and CSV export. Simulation, input errors, pause, unavailable direction and unreliable shift estimates have distinct visible states. The spectrogram and histories are bounded.

The olive/amber instrument presentation is isolated in `tactical.css`; measurement semantics and the continuous shift gradient are unchanged. A microphone-recovery panel exposes refresh, retry and replacement-input selection during driver errors. Device changes invalidate previous array geometry unless explicitly supplied again. Regular event polling retrieves five recent observations; the archive loads in user-requested pages instead of rebuilding 5,000 rows every two seconds. Browser requests time out, and socket loss invalidates displayed current measurements.

Live direction is experimental GCC-PHAT plus far-field least squares for a measured synchronized planar array. At least three non-collinear channels are required. Confidence/uncertainty are heuristic; narrowband signals and reflections can be ambiguous. A single microphone and independent unsynchronized devices do not supply the required spatial evidence.
