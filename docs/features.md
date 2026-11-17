# Implementation status — 0.3.1

| Capability | Status and boundary |
|---|---|
| Microphone capture | Existing process-isolated shared-device acquisition, bounded queues, cancellable startup, retry/recovery preserved. No live accuracy claim from this run. |
| Synthetic demo | Fully local; deterministic audio features and explicitly independent simulated bearing. No sound playback required. |
| FFT/STFT | Overlapping Hann FFT, peaks, RMS/peak level, centroid/bandwidth/flux, relative noise floor, band power and bounded spectrogram. |
| Baseline | Per-linear-bin bounded median/MAD calibration, optional clipped EWMA center adaptation, anomaly suppression, freeze/reset, atomic statistics. |
| Environmental states | Up to 32 reviewed saved profiles and similarity suggestions. Operator activation; automatic state-transition alert suppression remains unimplemented. |
| Anomalies | Narrow tones, energy additions/removals, band categories, tonal/broadband changes, UUID lifecycle, duration, heuristic temporal descriptors and UNKNOWN external events. |
| Event history | Existing SQLite migrated additively; 5,000 records; filtering, ordinal timeline, comparison, annotations and CSV. Timeline spacing represents event order, not elapsed wall time. |
| Signature memory | Up to 256 operator-labelled compact feature signatures. Distance is similarity, never confirmed source identity. |
| Dashboard | Existing olive/amber instrument identity and continuous signed-shift gradient preserved; responsive local charts, baseline/deviation overlays, profiles and review controls. |
| API | Versioned REST, authenticated LAN, same-origin sockets, local OpenAPI/index, request/rate/client bounds; legacy aliases preserved. |
| Stereo / direction | Two-microphone GCC-PHAT bearing pair integrated into the polar display, including delay, measured spacing/orientation, uncertainty and paired history. Shared-clock verification required; front/back and elevation unresolved. Existing planar array bearing preserved. No distance estimation. |
| Doppler research | Known-reference signed frequency difference, tolerance/continuous colors and unreliable states preserved. No arbitrary-motion inference. |
| ARGOS | Optional versioned ingestion, bounded visual observations/FOV, explicit temporal uncertainty, identity fields rejected. Real ARGOS compatibility needs integration testing. |
| External vibration | Independent Python adapter for sensor-unit RMS/peak; no acoustic/visual attribution. No hardware sensor transport installed. |
| Discovery | Optional mDNS with direct IP fallback. Cross-device discovery unverified. |
| Endpoint recovery | Optional authenticated, pinned Python selector with HTTPS fallback and LAN restoration. Browser remains same-origin. |
| Public deployment | Disabled. No TLS proxy, public role separation or internet deployment supplied. |
| Windows EXE | PyInstaller folder distribution built and locally smoke-tested without the development virtual environment. Clean-machine/signing/installer validation pending. |
| Multiresolution | Executable synthetic comparison supplied; simultaneous live fusion deferred. |
| Classification | Optional tonal/unknown characteristics only. No validated speech VAD, mechanical classification, speaker identity, object identification or modulation classifier. |

No raw audio recording/streaming is implemented. All capture is visible and stoppable.
Use only where participants have consented and you are authorized to monitor sound.
Digital values are not calibrated sound-pressure level. There is no military target
identification, physical source tracking or acoustic-to-person attribution.
