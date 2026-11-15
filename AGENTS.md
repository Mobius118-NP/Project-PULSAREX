# Repository instructions

Project: PULSAR Mk. II, an acoustic spectral analysis and environmental change detection application.

- Preserve the continuous frequency-shift colour gradient in docs/frequency-shift-indicator.md.
- Use Python 3.11+ with separate acquisition, DSP, application-server and dashboard layers.
- Work incrementally and validate implemented behavior with synthetic signals.
- Do not fabricate live bearings or measurements when hardware is unavailable.
- Require suitable synchronized array hardware for real direction estimates.
- Distinguish arbitrary source pitch changes from controlled Doppler measurements.
- Keep raw audio recording off by default and authenticate non-loopback dashboard access.
- Keep secrets, virtual environments, recordings and generated databases out of Git.
