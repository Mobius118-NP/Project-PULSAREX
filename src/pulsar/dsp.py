import math

import numpy as np
from scipy.signal import find_peaks


def shift_color(shift, limit=200.0, tolerance=2.0):
    """Continuous signed ramp with a continuous neutral plateau."""
    if shift is None or not math.isfinite(shift):
        return "#697585"
    if not 0 <= tolerance < limit:
        raise ValueError("Expected 0 <= tolerance < limit")
    value = min(1.0, max(0.0, (abs(shift) - tolerance) / (limit - tolerance)))
    stops = (
        [(66, 220, 151), (65, 149, 242), (146, 86, 244)]
        if shift < 0
        else [(66, 220, 151), (247, 208, 86), (246, 83, 91)]
    )
    index = min(1, int(value * 2))
    alpha = value * 2 - index
    rgb = [round(a + (b - a) * alpha) for a, b in zip(stops[index], stops[index + 1], strict=True)]
    return "#" + "".join(f"{c:02x}" for c in rgb)


def harmonic_groups(peaks, resolution):
    groups = []
    for peak in peaks[:16]:
        fundamental = peak["hz"]
        if any(
            abs(fundamental / g["fundamental_hz"] - round(fundamental / g["fundamental_hz"]))
            < max(0.025, resolution / g["fundamental_hz"])
            for g in groups
        ):
            continue
        members = []
        for other in peaks:
            ratio = other["hz"] / fundamental
            order = round(ratio)
            if 1 <= order <= 12 and abs(other["hz"] - order * fundamental) < max(
                2 * resolution, fundamental * 0.025
            ):
                members.append({"order": order, **other})
        if len(members) >= 2:
            groups.append(
                {
                    "fundamental_hz": fundamental,
                    "members": members,
                    "confidence": min(0.9, 0.35 + 0.12 * len(members)),
                }
            )
    return groups[:6]


class Analyzer:
    def __init__(self, config):
        self.config = config
        self.window = np.hanning(config.fft_size)
        self.freq = np.fft.rfftfreq(config.fft_size, 1 / config.sample_rate)
        self.edges = np.geomspace(config.min_frequency, config.max_frequency, config.display_bins + 1)
        self.centres = np.sqrt(self.edges[:-1] * self.edges[1:])
        # Multiple low-frequency display bins may share the same FFT bin.
        self.bin_ranges = [
            (
                max(1, np.searchsorted(self.freq, a)),
                min(len(self.freq), max(np.searchsorted(self.freq, b), np.searchsorted(self.freq, a) + 1)),
            )
            for a, b in zip(self.edges[:-1], self.edges[1:], strict=True)
        ]
        self.previous = None
        self.previous_fundamentals = []

    def analyze(self, samples):
        cfg = self.config
        x = np.asarray(samples, dtype=float)
        if x.ndim == 2:
            x = x[:, 0]  # Averaging array channels can cancel frequencies.
        if len(x) != cfg.fft_size or not np.isfinite(x).all():
            raise ValueError("Expected one finite FFT window")
        rms = float(np.sqrt(np.mean(x * x)))
        amplitude = np.abs(np.fft.rfft((x - x.mean()) * self.window)) * 2 / self.window.sum()
        amplitude[[0, -1]] *= 0.5
        db = 20 * np.log10(np.maximum(amplitude, 1e-7))
        noise = float(np.percentile(db[1:], 35))
        indices, _ = find_peaks(db, height=max(noise + 15, -85), prominence=7, distance=2)
        indices = [i for i in indices if cfg.min_frequency <= self.freq[i] <= cfg.max_frequency]
        indices = sorted(indices, key=lambda i: db[i], reverse=True)[:24]
        peaks = []
        for i in indices:
            left, middle, right = db[i - 1 : i + 2]
            denom = left - 2 * middle + right
            offset = float(np.clip(0.5 * (left - right) / denom, -0.5, 0.5)) if denom else 0
            peaks.append(
                {
                    "hz": round(float((i + offset) * cfg.sample_rate / cfg.fft_size), 3),
                    "dbfs": round(float(db[i]), 2),
                    "snr_db": round(float(db[i] - noise), 2),
                }
            )
        display = np.array([float(db[a:b].max()) if a < b else -140 for a, b in self.bin_ranges])
        centroid = float(np.sum(self.freq * amplitude) / max(amplitude.sum(), 1e-12))
        norm = amplitude / max(np.linalg.norm(amplitude), 1e-12)
        flux = float(np.linalg.norm(np.maximum(0, norm - self.previous))) if self.previous is not None else 0
        self.previous = norm
        groups = harmonic_groups(peaks, cfg.sample_rate / cfg.fft_size) if cfg.harmonics_enabled else []
        for group in groups:
            group["stability"] = any(
                abs(group["fundamental_hz"] - old) < cfg.sample_rate / cfg.fft_size * 2
                for old in self.previous_fundamentals
            )
        self.previous_fundamentals = [g["fundamental_hz"] for g in groups]
        candidates = [p for p in peaks if abs(p["hz"] - cfg.reference_hz) <= cfg.shift_range_hz]
        candidate = max(candidates, key=lambda p: p["dbfs"], default=None)
        ambiguous = (
            len(candidates) > 1
            and sorted((p["dbfs"] for p in candidates), reverse=True)[0]
            - sorted((p["dbfs"] for p in candidates), reverse=True)[1]
            < 6
        )
        reliable = bool(candidate and candidate["snr_db"] >= 20 and rms > 1e-5 and not ambiguous)
        shift = candidate["hz"] - cfg.reference_hz if candidate else None
        return {
            "frequencies": self.centres.round(2).tolist(),
            "spectrum_dbfs": display.round(2).tolist(),
            "rms_dbfs": round(20 * math.log10(max(rms, 1e-7)), 2),
            "centroid_hz": round(centroid, 2),
            "flux": round(flux, 4),
            "noise_floor_dbfs": round(noise, 2),
            "peaks": peaks,
            "harmonics": groups,
            "shift": {
                "hz": round(shift, 3) if shift is not None else None,
                "observed_hz": candidate["hz"] if candidate else None,
                "reference_hz": cfg.reference_hz,
                "reliable": reliable,
                "confidence": min(1, candidate["snr_db"] / 60) if reliable else 0,
                "status": "valid" if reliable else "ambiguous" if ambiguous else "unavailable",
                "color": shift_color(shift if reliable else None, cfg.shift_range_hz, cfg.zero_tolerance_hz),
                "interpretation": "controlled synthetic shift"
                if cfg.source == "simulation"
                else "frequency shift",
            },
        }


def estimate_bearing(samples, sample_rate, positions):
    """Experimental planar GCC-PHAT least-squares far-field bearing.

    Clockwise degrees from +Y (north), for a synchronized non-collinear array.
    Narrowband/multipath signals can be ambiguous; this is not source identity.
    """
    geometry = np.asarray(positions, dtype=float)
    if len(geometry) < 3:
        return {"available": False, "reason": "Calibrated synchronized array required"}
    x = np.asarray(samples, dtype=float)
    n = 2 ** int(np.ceil(np.log2(len(x) * 2)))
    delays, clarity = [], []
    reference = np.fft.rfft((x[:, 0] - x[:, 0].mean()) * np.hanning(len(x)), n)
    for channel in range(1, x.shape[1]):
        transform = np.fft.rfft((x[:, channel] - x[:, channel].mean()) * np.hanning(len(x)), n)
        cross = transform * reference.conj()
        gcc = np.fft.irfft(cross / np.maximum(np.abs(cross), 1e-12), n)
        max_lag = min(
            n // 2 - 1, int(np.ceil(np.linalg.norm(geometry[channel] - geometry[0]) / 343 * sample_rate)) + 1
        )
        corr = np.abs(np.concatenate((gcc[-max_lag:], gcc[: max_lag + 1])))
        index = int(np.argmax(corr))
        lag = index - max_lag
        offset = 0
        if 0 < index < len(corr) - 1:
            a, b, c = corr[index - 1 : index + 2]
            if a - 2 * b + c:
                offset = 0.5 * (a - c) / (a - 2 * b + c)
        delays.append((lag + offset) / sample_rate)
        clarity.append(float(corr[index] / max(corr.sum(), 1e-12)))
    vectors = geometry[1:] - geometry[0]
    direction, *_ = np.linalg.lstsq(vectors, -343 * np.array(delays), rcond=None)
    norm = float(np.linalg.norm(direction))
    residual = float(np.linalg.norm(vectors @ direction + 343 * np.array(delays)))
    confidence = min(1.0, min(clarity) * 2) * max(0, 1 - abs(1 - norm))
    if confidence < 0.1 or norm < 0.1:
        return {
            "available": False,
            "reason": "Array estimate unreliable or ambiguous",
            "confidence": confidence,
        }
    return {
        "available": True,
        "bearing_deg": round(math.degrees(math.atan2(direction[0], direction[1])) % 360, 1),
        "confidence": round(confidence, 3),
        "residual_m": residual,
        "experimental": True,
        "uncertainty_deg": round(max(5, (1 - confidence) * 90), 1),
    }
