# Frequency-shift indicator

User decision, 15 November 2026: the Doppler/spectrum-shift indicator is gradient based, with smooth colour changes.

## Mapping

- Signed shift: observed frequency minus known reference frequency, in Hz.
- Negative: blend from green through blue to violet as negative magnitude increases.
- Approximately zero: green, with configurable zero-shift tolerance.
- Positive: blend from green through yellow/orange to red as positive magnitude increases.
- Interpolate continuously between colour stops. No discrete red/green/blue threshold jumps.
- Keep the mapping continuous at the edges of the configurable neutral region.
- Make the displayed shift range configurable; clamp colours at its limits while retaining the actual numerical shift.
- Show a continuous gradient legend with signed Hz labels and a zero marker.
- Any temporal smoothing affects the display only; preserve the measured numerical values and history.

## Measurement states

Keep confidence separate from signed colour. Missing, invalid or unreliable estimates must have an explicit unavailable/low-confidence state rather than looking like a valid zero shift. Retain a signed numerical readout so colour is not the only signal.

Call the result frequency/spectrum shift unless a known reference and controlled experimental assumptions justify a Doppler interpretation. Approaching/receding labels are conditional on those assumptions.

## Verification when implemented

Check both signs, exact zero, tolerance boundaries, range saturation and invalid input. Sweep continuously across the range to verify the absence of visible colour jumps.
