"""Experimental shared-clock two-microphone bearings in an assumed horizontal plane."""
import math

import numpy as np


def pair_geometry(spacing_m, axis_deg=90.0, positions=None):
    """Axis is clockwise from +Y, from channel 0 toward channel 1."""
    if positions is not None and len(positions):
        geometry = np.asarray(positions, dtype=float)
        if geometry.shape != (2, 2) or not np.isfinite(geometry).all():
            raise ValueError("Two finite [x,y] microphone positions required")
        vector = geometry[1]-geometry[0]
        spacing_m = float(np.linalg.norm(vector))
        axis_deg = math.degrees(math.atan2(vector[0], vector[1])) % 360
    if not math.isfinite(spacing_m) or not .01 <= spacing_m <= 10:
        raise ValueError("Microphone spacing must be 0.01-10 metres")
    if not math.isfinite(axis_deg) or not 0 <= axis_deg < 360:
        raise ValueError("Pair axis must be 0-359.999 degrees")
    return float(spacing_m), float(axis_deg)


def bearing_candidates(delay, spacing_m, axis_deg=90.0):
    # tau = t(channel1)-t(channel0) = -dot(pair, source_unit_vector)/c.
    offset = math.degrees(math.acos(float(np.clip(-delay*343/spacing_m, -1, 1))))
    return [(axis_deg-offset) % 360, (axis_deg+offset) % 360]


def stereo_delay(samples, sample_rate, spacing_m, synchronized=False, axis_deg=90.0, positions=None):
    if not synchronized:
        return {"available": False, "reason": "Shared-clock synchronization must be verified by the operator"}
    try:
        spacing_m, axis_deg = pair_geometry(spacing_m, axis_deg, positions)
        if not math.isfinite(sample_rate) or sample_rate <= 0:
            raise ValueError("Invalid sample rate")
    except (ValueError, TypeError) as exc:
        return {"available": False, "reason": str(exc)}
    x = np.asarray(samples, dtype=float)
    if x.ndim != 2 or x.shape[1] != 2 or len(x) < 128 or not np.isfinite(x).all():
        return {"available": False, "reason": "Two finite synchronized channels required"}
    x = x-x.mean(axis=0)
    rms = np.sqrt(np.mean(x*x, axis=0))
    if np.min(rms) < 1e-6:
        return {"available": False, "reason": "Silent channel"}
    normalized = x / rms
    # At exact broadside a perfect copy is indistinguishable from duplication.
    duplicate_error = min(np.mean((normalized[:, 0]-normalized[:, 1])**2),
                          np.mean((normalized[:, 0]+normalized[:, 1])**2))
    if duplicate_error < 1e-5:
        return {"available": False, "reason": "Duplicated or effectively mono input; zero-delay broadside cannot be verified"}
    size = 2**int(np.ceil(np.log2(len(x)*2)))
    transforms = np.fft.rfft(x*np.hanning(len(x))[:, None], size, axis=0)
    power = np.abs(transforms[:, 0])**2
    flatness = np.exp(np.log(np.maximum(power[1:], 1e-20)).mean()) / max(power[1:].mean(), 1e-20)
    if flatness < .005:
        return {"available": False, "reason": "Narrowband delay is ambiguous"}
    cross = transforms[:, 1]*transforms[:, 0].conj()
    gcc = np.fft.irfft(cross/np.maximum(np.abs(cross), 1e-12), size)
    max_samples = spacing_m/343*sample_rate
    if math.ceil(max_samples)+1 >= len(x)//4:
        return {"available": False, "reason": "FFT window too short for this microphone spacing"}
    limit = int(np.ceil(max_samples))+1
    lags = np.arange(-limit, limit+1)
    values = np.abs(gcc[lags % size])
    index = int(values.argmax())
    offset = 0.0
    if 0 < index < len(values)-1:
        left, middle, right = values[index-1:index+2]
        denom = left-2*middle+right
        if denom:
            offset = float(np.clip(.5*(left-right)/denom, -.5, .5))
    lag = float(lags[index])+offset
    delay = lag/sample_rate
    clarity = float(values[index]/max(values.sum(), 1e-12))
    if abs(lag) > max_samples+.5 or clarity < .15:
        return {"available": False, "reason": "Unresolved or physically inconsistent delay"}
    delay = float(np.clip(delay, -spacing_m/343, spacing_m/343))
    angles = bearing_candidates(delay, spacing_m, axis_deg)
    # Quantization/peak-width allowance, not a calibrated confidence interval.
    uncertainty_seconds = max(1.0, 2*(1-clarity))/sample_rate
    lower = bearing_candidates(delay-uncertainty_seconds, spacing_m, axis_deg)
    upper = bearing_candidates(delay+uncertainty_seconds, spacing_m, axis_deg)
    uncertainty = max(abs((edge-center+180) % 360-180)
                      for limits in (lower, upper) for edge, center in zip(limits, angles, strict=True))
    return {"available": True, "mode": "two_microphone", "experimental": True, "ambiguous": True,
            "bearing_deg": None, "possible_bearings_deg": [round(a, 1) % 360 for a in angles],
            "axis_bearing_deg": axis_deg, "spacing_m": spacing_m,
            "delay_seconds": delay, "delay_samples": int(lags[index]), "fractional_delay_samples": lag,
            "confidence": round(min(.9, clarity), 3), "uncertainty_seconds": uncertainty_seconds,
            "uncertainty_deg": round(max(1.0, uncertainty), 1),
            "ambiguity": "Front/back unresolved in the assumed horizontal plane; no distance or elevation estimate",
            "synchronization": "Operator-verified shared clock and channel alignment; data alone cannot certify synchronization"}
