# Acoustic evidence and baseline model

The baseline operates on every linear FFT bin, not on the max-pooled logarithmic
chart. Raw spectra are preserved. This is background modeling, not noise removal.

## Median / MAD and optional EWMA hybrid

At initialization (unless disabled) or manual calibration, collect up to 512 spectra
in a uniform reservoir. Memory therefore remains bounded even with a long calibration.
Per-bin center is the median of log magnitudes. Variation is `max(2 dB, 1.4826*MAD)`.
The robust center tolerates a minority of transient-contaminated calibration frames.
A persistent event occupying most calibration frames will be learned: operators must
choose a representative interval and review saved environmental states.

For each bin, compute signed `delta_db = observed_dbfs - center_dbfs` and
`robust_z = abs(delta_db)/variation_db`. Detection requires BOTH the configured
dB threshold and z threshold, within the selected frequency range. The stronger
of current and baseline levels must exceed -90 dBFS to avoid reacting to numerical
floor fluctuations. This digital floor is a practical gate, not a calibrated
microphone sensitivity specification. Defaults are 12 dB and z=4; scores are
heuristics, not p-values or posterior probabilities. Overlapping FFT windows and
neighboring bins are correlated. No independent multiple-testing guarantee is claimed.

When enabled, center adaptation uses a clipped, time-based EWMA:

```text
alpha = 1 - exp(-dt / adaptation_seconds)
center += alpha * clip(observed - center, -variation, variation)
```

`dt` is capped at one second and reset on stream discontinuity. The entire frame's
adaptation is suppressed if any bin passes the baseline anomaly gate. Freeze
overrides adaptation. Adaptation defaults off. Variation is calibrated MAD and
stays fixed until recalibration; this is not an online EWMA variance estimator.
This conservative hybrid can resist new tones but can also remain frozen after a
real permanent state change. Review and explicitly activate/recalibrate a profile.

The baseline gate covers the whole FFT for conservative adaptation. Event reports
are restricted to the selected analysis range. This can suppress adaptation for
out-of-range energy; it cannot create an out-of-range event claim.

## Frequency changes of interest

Detect additions/removals, increased/reduced energy, pitch changes (changed spectral
bins), and harmonic energy changes. One resolvable tonal bin can trigger detection;
there is no minimum changed-display-bin fraction. Configurable band boundaries
default to low <250 Hz, mid 250-4000 Hz and high >4000 Hz, clipped to the analysis
range and Nyquist. A microphone's real response must be supplied by its operator.
Sampling at 48 kHz does not establish that the microphone measures all frequencies
up to 24 kHz accurately. Gain, automatic gain control, mounting and device changes
can change the baseline and require recalibration.

An event has a stable UUID, signed change, score, original-vs-baseline compact
spectral evidence, peak, affected range and duration. Active records update at
cooldown intervals. Return to baseline completes the event; stopping acquisition
marks it interrupted. Duration is acoustic observation time, not physical-object
lifetime. Multiple simultaneous deviations share a spectral event; the detector
does not separate physical sources. Threshold chatter can split events. Transient,
persistent, increasing/decreasing and repeating/intermittent descriptors are simple
heuristics over bounded history, not a learned temporal classifier.

Named profiles are limited to 32. Saved profiles are compared conservatively and
matching known states are suggested; activation remains explicit. Automatic state
transition suppression is intentionally not implemented because it could hide a
meaningful deviation. Profile statistics are input/FFT specific. Old v0.2 baseline
files are preserved but require recalibration because the detector now uses linear
bins. Existing SQLite event rows remain readable through an additive migration.

## Measurements and experiments

FFT magnitudes use Hann coherent-gain normalization, in relative dBFS. Band powers
use one-sided Parseval normalization (`sum(|FFT|^2)/(N*sum(window^2))`, doubled except
DC/Nyquist) and 10log10, also relative to digital full-scale. Band power and peak
magnitude are different quantities. Centroid/bandwidth are amplitude-weighted.
The noise floor is a relative spectral percentile, not acoustic ambient SPL.
An additional 150 ms EWMA spectrum is exposed for consumers needing temporal display
smoothing; detection and the standard spectrum remain unsmoothed.

Harmonic grouping is optional. Two-frame fundamental consistency and component
changes are heuristic; missing fundamentals are not inferred reliably. Nonharmonic
and ambiguous signals remain valid observations. Optional characterization currently
only reports tonal or unknown characteristics; speech VAD, mechanical-source
classification and amplitude-modulation analysis are not implemented.

Stereo GCC-PHAT requires operator-verified shared-clock hardware, rejects silent,
duplicated and narrowband input, and reports delay plus two ambiguous bearings.
Signal data alone cannot certify channel synchronization. No distance estimate.
Planar bearing requires the existing calibrated non-collinear array interface.
The assumed speed of sound is 343 m/s, not compensated for temperature.

Frequency shift is observed minus known reference, with the preserved continuous
red/green/blue-violet ramp. It is not proof of Doppler or motion. See the existing
[indicator specification](frequency-shift-indicator.md).

`examples/multiresolution.py` investigates 1024/4096/16384-sample Hann STFTs: at
48 kHz, resolutions are 46.875/11.719/2.930 Hz, while frame spans are
21.33/85.33/341.33 ms. A larger FFT helps distinguish close low-frequency tones but
smears short transients. Production retains one configurable overlapping STFT;
simultaneous multiresolution fusion remains research, avoiding unvalidated blending.

Method references: [SciPy MAD definition](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.median_abs_deviation.html).
