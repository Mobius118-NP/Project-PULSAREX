# Two-microphone acoustic bearing — 0.3.1

Two microphones are sufficient for an experimental ambiguous bearing measurement.
PULSAREX estimates inter-channel time delay using GCC-PHAT and converts it using
the measured spacing and pair orientation. The polar panel draws **both** candidate
directions, uncertainty sectors and bounded history. A third microphone is no
longer required for the two-candidate mode. Existing non-collinear arrays remain supported.

## Configure

1. Choose a microphone/interface providing two distinct channels on a shared clock.
   Connect both microphones to that interface; select input channels=2. Independently
   clocked USB microphones do not become synchronized by capturing them together.
2. In Configuration, check **I verified two distinct channels on one shared-clock
   input** only after confirming the hardware/channel routing. Matched or calibrated
   channel latency is assumed; the application cannot certify synchronization from
   arbitrary sound alone. Processed laptop arrays may expose duplicated mono data.
3. Enter physical spacing in metres, for example **0.15** for 15 cm.
4. Enter the axis from channel 0 toward channel 1, clockwise from diagram north.
   **90 degrees** means channel 1 is east/right of channel 0; **0** means north/up.
   These are local diagram coordinates, not an automatically measured compass heading.
5. Apply. Alternatively, provide two `[x,y]` positions in metres; these override the
   spacing/axis fields. Reconfirm synchronization after switching input devices or
   channel count. Single-channel spectral analysis remains available independently.

```toml
source = "microphone"
channels = 2
stereo_synchronized = true
stereo_spacing_m = 0.15
stereo_axis_deg = 90.0
# Optional alternative geometry (channel order matters):
# mic_positions = [[0.0, 0.0], [0.15, 0.0]]
```

## Measurement meaning

For pair vector `d` from channel 0 to channel 1 and source-direction unit vector `u`,
the far-field arrival-time difference is `tau = -dot(d,u)/343` seconds. Sound speed
343 m/s is assumed. Delay sign follows `t(channel1)-t(channel0)`. The pair-axis
projection yields two mirror-symmetric bearings in an assumed horizontal plane.
In unrestricted 3D the ambiguity is a cone, not just two points. Elevation, distance
and front/back cannot be resolved by this pair alone. No intensity-based distance
or arbitrary choice between the two directions is displayed.

Sub-sample interpolation refines the correlation peak; uncertainty still includes
at least one sample of delay allowance, transformed nonlinearly into an angle.
Near endfire angular uncertainty grows. Confidence is a correlation heuristic,
not a calibrated probability; reflections, multiple sources, unknown elevation,
sound speed and microphone/channel phase differences can introduce larger errors.

Silent channels, identical/inverted duplicated mono channels, narrowband-only sound,
weak correlation, impossible delays, unsuitable spacing/window combinations and
unverified synchronization yield **unavailable**. A perfectly identical broadside
signal cannot be distinguished from duplicated mono; withholding it is conservative.
Stopping capture invalidates both live direction and stereo delay readouts.

REST/WebSocket snapshots expose `direction.mode = "two_microphone"`,
`possible_bearings_deg`, `uncertainty_deg`, `delay_seconds`, `confidence` and explicit
ambiguity. `bearing_deg` is null rather than selecting an unjustified single bearing.
In simulation, two channels show a labelled pair of synthetic UI bearings, independent
of the generated audio, and never report a fabricated measured stereo delay.

Synthetic validation covers several bearings, rotated geometry, channel polarity,
invalid geometry/sampling, stale data, synchronization reset and API/streaming. Real
microphone accuracy still requires a calibrated pair and hardware measurements.

Method reference: [GCC-PHAT time delay and pair arrival angle](https://www.mathworks.com/help/phased/ref/gccphat.html).
