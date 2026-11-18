# Implementation status — 0.5.0

| Capability | Status and boundary |
|---|---|
| Microphone capture | Existing process-isolated shared-device acquisition, bounded queues, cancellable startup, retry/recovery preserved. No live accuracy claim from this run. |
| Synthetic demo | Fully local; deterministic audio features and explicitly independent simulated bearing. No sound playback required. |
| FFT/STFT | Overlapping Hann FFT, peaks, RMS/peak level, centroid/bandwidth/flux, relative noise floor, band power and bounded spectrogram. |
| Baseline | Per-linear-bin bounded median/MAD calibration, optional clipped EWMA center adaptation, anomaly suppression, freeze/reset, atomic statistics. |
| Environmental states | Up to 32 reviewed saved profiles and similarity suggestions. Operator activation; automatic state-transition alert suppression remains unimplemented. |
| Anomalies | Narrow tones, energy additions/removals, band categories, tonal/broadband changes, UUID lifecycle, duration, heuristic temporal descriptors and UNKNOWN external events. |
| Event history | Existing SQLite migrated additively; 5,000 records; filtering, ordinal timeline, comparison, annotations, CSV and confirmed Clear archive. Queued old writes cannot resurrect deleted events; reviewed signatures remain. Timeline spacing represents event order, not elapsed wall time. |
| Signature memory | Up to 256 operator-labelled compact feature signatures. Distance is similarity, never confirmed source identity. |
| Dashboard | Existing olive/amber instrument identity and continuous signed-shift gradient preserved; responsive local charts, baseline/deviation overlays, profiles and review controls. |
| API | Versioned REST, six-digit LAN PIN with shared failed-guess limits and random browser sessions, same-origin sockets, local OpenAPI/index, request/rate/client bounds. Routes and six-digit token-field alias preserved; old long secrets require replacement. |
| Stereo / direction | Two-microphone GCC-PHAT bearing pair integrated into the polar display, including delay, measured spacing/orientation, uncertainty and paired history. Shared-clock verification required; front/back and elevation unresolved. Existing planar array bearing preserved. No distance estimation. |
| Doppler research | Known-reference signed frequency difference, tolerance/continuous colors and unreliable states preserved. No arbitrary-motion inference. |
| ARGOS camera / PPI | Local ARGOS detector/tracker reused in isolated capture process; live viewing window, assumed 78° pinhole projection, operator heading, direction-only purple vectors, optional enrolled IDs, explicit catalogue controls, bounded jitter playback and stale detection expiry. Camera 0 captured successfully. Real identity accuracy and remote LAN video unvalidated. See [setup](argos-integration.md). |
| External visual ingestion | Older versioned ingestion remains separate, with bounded observations/FOV and explicit temporal uncertainty; identity fields rejected on that external API. |
| External vibration | Independent Python adapter for sensor-unit RMS/peak; no acoustic/visual attribution. No hardware sensor transport installed. |
| Discovery | Optional mDNS with direct IP fallback. Cross-device discovery unverified. |
| Endpoint recovery | Optional authenticated, pinned Python selector with HTTPS fallback and LAN restoration. Browser remains same-origin. |
| Public deployment | Disabled. No TLS proxy, public role separation or internet deployment supplied. |
| Windows EXE | Earlier PyInstaller distribution remains available; current 0.5.0 integration runs from the source GUI launcher. New EXE packaging deferred. Clean-machine/signing/installer validation pending. |
| Multiresolution | Executable synthetic comparison supplied; simultaneous live fusion deferred. |
| Classification | Optional tonal/unknown characteristics only. No validated speech VAD, mechanical classification, speaker identity, object identification or modulation classifier. |

No raw audio recording/streaming is implemented. All capture is visible and stoppable.
Use only where participants have consented and you are authorized to monitor sound.
Digital values are not calibrated sound-pressure level. There is no military target
identification, physical source tracking or acoustic-to-person attribution.

The native GUI includes Local/LAN startup, generated masked six-digit PINs,
port/source/TOML controls, open/copy dashboard links, responsive status and managed
Stop/close. See [GUI details](gui-launcher.md). Console operation remains available.
