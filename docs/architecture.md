# Architecture

`audio.py` acquires float32 blocks from a local microphone or deterministic synthetic source. The PortAudio callback copies to a bounded eight-block queue and counts overruns. A worker performs analysis, retries failed input and releases the stream on stop. Windows automatic input selection prefers the system WASAPI input. Explicit device selections are preserved.

`dsp.py` applies a Hann window and FFT to a sliding frame, estimates peak frequencies, amplitude-normalized dBFS, spectral flux, amplitude-weighted centroid and relative noise floor. Log bins preserve local maxima. Sample rate and FFT size determine actual resolution; interpolated peak readouts do not add physical resolution.

Harmonic grouping is optional and heuristic. Frequency-shift estimates require a significant peak in the configured reference window. Competing similarly strong tones produce an ambiguous state. The continuous colour ramp has a green neutral plateau and continuous joins at its boundaries. Numerical measurements are not smoothed.

`baseline.py` uses online mean/variance during timed calibration. Quiet-frame adaptation is slow; significant deviations are excluded. Statistics are written atomically and checked against source/spectral settings before reuse.

`storage.py` detects positive and negative spectral deviations, applies a cooldown and stores observations in SQLite with WAL and locking. Retention is bounded to 5,000 rows. Duration is elapsed deviation time at emission, not a completed-event duration. Scores are heuristics, not classification probabilities.

`engine.py` owns acquisition, the sliding window, latest frame and bounded shift/bearing histories. Analysis runs at the hop cadence. Dashboard snapshots publish at an independent update rate. Slow browsers receive the newest snapshot rather than a queue. WebSocket writes time out after two seconds.

`server.py` exposes REST controls and WebSockets. Loopback is the default; LAN binding requires a token. Same-origin checks protect browser controls and sockets. Dashboard scripts and charts are served locally with no CDN or telemetry.

`dashboard/` provides responsive canvas instruments, controls, event history and CSV export. Simulation, input errors, pause, unavailable direction and unreliable shift estimates have distinct visible states. The spectrogram and histories are bounded.

Live direction is experimental GCC-PHAT plus far-field least squares for a measured synchronized planar array. At least three non-collinear channels are required. Confidence/uncertainty are heuristic; narrowband signals and reflections can be ambiguous. A single microphone and independent unsynchronized devices do not supply the required spatial evidence.
