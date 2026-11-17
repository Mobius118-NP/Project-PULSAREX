import re
from pathlib import Path
from zipfile import BadZipFile

import numpy as np


class Baseline:
    """Bounded log-spectrum median/MAD calibration; original spectra are never filtered."""

    def __init__(self, bins, duration=5.0, adaptation_seconds=300.0, sensitivity=4.0):
        self.bins = bins
        self.duration = duration
        self.mean = np.zeros(bins)
        self.m2 = np.zeros(bins)
        self.count = 0
        self.started = None
        self.ready = False
        self.calibrating = False
        self.saved = False
        self.progress = 0.0
        self.elapsed = 0.0
        self.last_update = None
        self.dirty = False
        self.scale = np.full(bins, 2.0)
        self.frozen = False
        self.adaptation_seconds = adaptation_seconds
        self.sensitivity = sensitivity
        self.samples = np.empty((512, bins), dtype=np.float32)
        self.rng = np.random.default_rng(42)
        self.last_adapt = None
        self.adaptation_suppressed = False

    def calibrate(self, now):
        if len(self.samples) != 512:
            self.samples = np.empty((512, self.bins), dtype=np.float32)
        self.started = now
        self.count = 0
        self.mean.fill(0)
        self.m2.fill(0)
        self.ready = False
        self.saved = False
        self.calibrating = True
        self.progress = 0.0
        self.elapsed = 0.0
        self.last_update = None
        self.scale.fill(2.0)
        self.dirty = False
        self.last_adapt = None

    def pause(self):
        """Do not count time without contiguous input toward calibration."""
        self.last_update = None
        self.last_adapt = None

    def update(self, spectrum, now, adapt=False, threshold=12.0):
        x = np.asarray(spectrum, dtype=float)
        if x.shape != (self.bins,) or not np.isfinite(x).all():
            raise ValueError("Baseline requires a finite spectrum with matching bins")
        if self.calibrating:
            if self.last_update is not None:
                self.elapsed += max(0.0, now - self.last_update)
            self.last_update = now
            self.count += 1
            # Uniform reservoir sampling bounds memory independently of calibration length.
            slot = self.count - 1 if self.count <= len(self.samples) else self.rng.integers(self.count)
            if slot < len(self.samples):
                self.samples[slot] = x
            self.progress = min(1, self.elapsed / self.duration)
            if self.progress >= 1 and self.count >= 2:
                reservoir = self.samples[:min(self.count, len(self.samples))]
                self.mean = np.median(reservoir, axis=0).astype(float)
                self.scale = np.maximum(2.0, 1.4826 * np.median(np.abs(reservoir - self.mean), axis=0))
                self.m2 = self.scale ** 2 * (self.count - 1)
                self.ready = True
                self.calibrating = False
                self.dirty = True
        deviation = x - self.mean if self.ready else np.zeros(self.bins)
        dt = max(0, min(1.0, now - self.last_adapt)) if self.last_adapt is not None else 0
        self.last_adapt = now
        # Suppress the entire update on an anomalous frame, including unaffected bins.
        # This prevents a new tone being gradually normalized while it is active.
        self.adaptation_suppressed = bool(self.ready and np.any(self.changed(x, threshold)))
        if self.ready and adapt and not self.frozen and not self.adaptation_suppressed:
            alpha = -np.expm1(-dt / self.adaptation_seconds)
            self.mean += alpha * np.clip(deviation, -self.scale, self.scale)
            self.dirty = True
        return deviation

    def changed(self, spectrum, threshold=12.0):
        x = np.asarray(spectrum)
        delta = np.abs(x - self.mean)
        return (delta >= threshold) & (delta / self.scale >= self.sensitivity) & (np.maximum(x, self.mean) > -90)

    def status(self):
        return {
            "ready": self.ready,
            "calibrating": self.calibrating,
            "progress": round(self.progress, 3),
            "frames": self.count,
            "mean_dbfs": self.mean.round(2).tolist() if self.ready else None,
            "variation_db": self.scale.round(2).tolist() if self.ready else None,
            "method": "log-spectrum median / scaled MAD (2 dB minimum)",
            "frozen": self.frozen,
            "adaptation_suppressed": self.adaptation_suppressed,
        }

    def save(self, path, signature):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.with_suffix(".tmp").open("wb") as output:
            np.savez(output, mean=self.mean, m2=self.m2, scale=self.scale,
                     count=self.count, signature=signature, frozen=self.frozen)
        path.with_suffix(".tmp").replace(path)
        self.saved = True
        self.dirty = False

    def load(self, path, signature):
        try:
            with np.load(path, allow_pickle=False) as data:
                if (
                    str(data["signature"]) != signature
                    or data["mean"].shape != (self.bins,)
                    or data["m2"].shape != (self.bins,)
                    or data["count"].shape != ()
                ):
                    return False
                if (
                    not np.isfinite(data["mean"]).all()
                    or not np.isfinite(data["m2"]).all()
                    or np.any(data["m2"] < 0)
                    or int(data["count"]) < 2
                ):
                    return False
                self.mean = data["mean"].copy()
                self.m2 = data["m2"].copy()
                self.count = int(data["count"])
                scale = data["scale"] if "scale" in data else np.sqrt(self.m2 / max(1, self.count - 1))
                if scale.shape != (self.bins,) or not np.isfinite(scale).all() or np.any(scale < 0):
                    return False
                self.scale = np.maximum(2.0, scale)
                self.frozen = bool(data["frozen"]) if "frozen" in data else False
            self.ready = self.count >= 2
            self.progress = 1.0 if self.ready else 0.0
            self.saved = self.ready
            self.samples = np.empty((0, self.bins), dtype=np.float32)
            return self.ready
        except (OSError, ValueError, KeyError, EOFError, BadZipFile):
            return False


class Profiles:
    """Named operator-approved environmental states; never silently learn a new state."""

    def __init__(self, directory):
        self.directory = Path(directory)

    def path(self, name):
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,47}", name):
            raise ValueError("Profile names need 1-48 letters, digits, underscores or hyphens")
        return self.directory / f"{name}.npz"

    def names(self):
        return sorted(p.stem for p in self.directory.glob("*.npz"))[:32]

    def save(self, name, baseline, signature):
        path = self.path(name)
        if not baseline.ready:
            raise ValueError("Calibrate before saving a profile")
        if not path.exists() and len(self.names()) >= 32:
            raise ValueError("Profile limit (32) reached")
        baseline.save(path, signature)

    def load(self, name, bins, duration, signature):
        baseline = Baseline(bins, duration)
        if not baseline.load(self.path(name), signature):
            raise ValueError("Profile is missing, corrupt or incompatible with this input/FFT")
        return baseline
