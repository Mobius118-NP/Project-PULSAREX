"""Baseline-relative observations, independent of storage and source classification."""
from collections import deque
from uuid import uuid4

import numpy as np


class EventDetector:
    def __init__(self, threshold=12.0, cooldown=3.0):
        self.threshold, self.cooldown = threshold, cooldown
        self.last_event = -float("inf")
        self.previous_peak = None
        self.onset = None
        self.active = None
        self.history = deque(maxlen=24)
        self.last_active = None
        self.previous_harmonics = set()
        self.occurrences = deque(maxlen=16)

    def reset(self):
        self.onset = self.active = self.last_active = None
        self.previous_peak = None
        self.previous_harmonics.clear()
        self.history.clear()

    def detect(self, frame, deviation, ready, now, timestamp, scale=None, sensitivity=4.0,
               profile_id="default", sensor_id="local-acoustic-01", band_edges=(250, 4000)):
        if not ready:
            self.reset()
            return None
        delta = np.asarray(deviation)
        frequencies = np.asarray(frame.get("_linear_frequencies", frame["frequencies"]))
        spectrum = np.asarray(frame.get("_linear_dbfs", frame["spectrum_dbfs"]))
        if len(frequencies) != len(delta):  # Backward-compatible callers using log display bins.
            frequencies, spectrum = np.asarray(frame["frequencies"]), np.asarray(frame["spectrum_dbfs"])
        variation = np.full_like(delta, 2.0) if scale is None else np.asarray(scale)
        lower, upper = frame.get("analysis_range_hz", [frame["frequencies"][0], frame["frequencies"][-1]])
        z = np.abs(delta) / variation
        changed = (np.abs(delta) >= self.threshold) & (z >= sensitivity)
        changed &= np.maximum(spectrum, spectrum-delta) > -90
        changed &= (frequencies >= lower) & (frequencies <= upper)
        # A single resolvable tonal bin is evidence; log-display-bin fractions are not.
        active = bool(changed.any())
        if not active:
            if self.active is None:
                return None
            event = {**self.active, "state": "completed", "ended_at": timestamp,
                     "duration_seconds": round(max(0, self.last_active - self.onset), 3)}
            self.reset()
            return event
        magnitude = float(np.percentile(np.abs(delta[changed]), 80))
        signed = float(np.median(delta[changed]))
        if self.onset is None:
            self.onset = now
            self.occurrences.append(now)
        self.last_active = now
        self.history.append((now, magnitude))
        elapsed = now-self.onset
        descriptors = ["persistent" if elapsed >= 2 else "transient"]
        if len([t for t in self.occurrences if now-t <= 30]) >= 3:
            descriptors.extend(["repeating", "intermittent"])
        if len(self.history) > 2 and self.history[-1][0]-self.history[0][0] >= 0.5:
            trend = self.history[-1][1]-self.history[0][1]
            if abs(trend) > 3:
                descriptors.append("increasing" if trend > 0 else "decreasing")
        bands = {"low" if f < band_edges[0] else "mid" if f < band_edges[1] else "high"
                 for f in frequencies[changed]}
        band = next(iter(bands)) if len(bands) == 1 else "broadband"
        category = "broadband transient" if changed.mean() > .35 and frame["flux"] > .2 else "spectral change"
        peak = frame.get("peaks", [{}])[0].get("hz") if frame.get("peaks") else None
        if peak and self.previous_peak and abs(peak-self.previous_peak) > frame.get("resolution_hz", 12)*2:
            category = "tonal change"
        if peak:
            self.previous_peak = peak
        harmonics = {round(p["hz"]/max(frame.get("resolution_hz", 12), 1))
                     for g in frame.get("harmonics", []) for p in g["members"]}
        evidence = {"changed_bins": int(changed.sum()), "peak_z": round(float(z[changed].max()), 3),
                    "harmonic_components_changed": len(harmonics.symmetric_difference(self.previous_harmonics)),
                    "flux": frame["flux"], "band_energy": frame.get("band_energy", {})}
        self.previous_harmonics = harmonics
        event = {
            "schema_version": 1, "event_id": self.active["event_id"] if self.active else str(uuid4()),
            "timestamp": self.active["timestamp"] if self.active else timestamp, "updated_at": timestamp,
            "sensor_id": sensor_id, "baseline_profile_id": profile_id, "category": category,
            "anomaly_type": f"{band.upper()}_ANOMALY" if bands else "UNKNOWN_ANOMALY",
            "frequency_band": band, "peak_frequency_hz": peak,
            "band_hz": [round(float(frequencies[changed].min()), 2), round(float(frequencies[changed].max()), 2)],
            "change_db": round(magnitude, 2), "signed_change_db": round(signed, 2),
            "duration_seconds": round(elapsed, 3), "temporal_characteristics": descriptors,
            "score": round(min(1, magnitude/(self.threshold*3)), 3), "state": "active",
            "source": frame.get("source", "unknown"), "evidence": evidence,
            "features": [round(frame.get("centroid_hz", 0)/24000, 5),
                         round(frame.get("bandwidth_hz", 0)/24000, 5),
                         round(frame.get("rms_dbfs", -140)/140, 5), round(frame["flux"], 5)],
            "uncertainty": "Heuristic detection score; no physical source attribution",
        }
        self.active = event
        valid = np.flatnonzero((frequencies >= lower) & (frequencies <= upper))
        # Keep the strongest changed components alongside a compact log-spaced profile.
        strongest = np.flatnonzero(changed)[np.argsort(np.abs(delta[changed]))[-16:]]
        indices = np.unique(np.concatenate((valid[np.geomspace(1, len(valid), 48).astype(int)-1], strongest)))
        event["spectral_evidence"] = {"frequencies_hz": frequencies[indices].round(2).tolist(),
                                       "current_dbfs": spectrum[indices].round(2).tolist(),
                                       "baseline_dbfs": (spectrum-delta)[indices].round(2).tolist()}
        # Coarse spectral shape supplements aggregate features; still cannot identify a source.
        event["features"] += (np.asarray(frame["spectrum_dbfs"])[::max(1, len(frame["spectrum_dbfs"])//32)][:32]/140).round(5).tolist()
        if now-self.last_event < self.cooldown:
            return None
        self.last_event = now
        return event


def characterize(frame):
    """Optional measurable broad characteristics only. No VAD or source classifier."""
    if frame.get("harmonics"):
        return {"label": "tonal sound", "experimental": True, "score": 0.6}
    return {"label": "unknown acoustic event", "experimental": True, "score": 0.0}
