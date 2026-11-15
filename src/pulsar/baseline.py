from pathlib import Path
from zipfile import BadZipFile

import numpy as np


class Baseline:
    def __init__(self, bins, duration=5.0):
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

    def calibrate(self, now):
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

    def pause(self):
        """Do not count time without contiguous input toward calibration."""
        self.last_update = None

    def update(self, spectrum, now, adapt=False, threshold=12.0):
        x = np.asarray(spectrum, dtype=float)
        if x.shape != (self.bins,) or not np.isfinite(x).all():
            raise ValueError("Baseline requires a finite spectrum with matching bins")
        if self.calibrating:
            if self.last_update is not None:
                self.elapsed += max(0.0, now - self.last_update)
            self.last_update = now
            self.count += 1
            delta = x - self.mean
            self.mean += delta / self.count
            self.m2 += delta * (x - self.mean)
            self.progress = min(1, self.elapsed / self.duration)
            if self.progress >= 1 and self.count >= 2:
                self.ready = True
                self.calibrating = False
                self.dirty = True
        deviation = x - self.mean if self.ready else np.zeros(self.bins)
        if self.ready and adapt and np.max(np.abs(deviation)) < threshold / 2:
            # Conservative adaptation of quiet frames only; transients excluded.
            self.mean += 0.001 * (x - self.mean)
            self.dirty = True
        return deviation

    def status(self):
        return {
            "ready": self.ready,
            "calibrating": self.calibrating,
            "progress": round(self.progress, 3),
            "frames": self.count,
            "mean_dbfs": self.mean.round(2).tolist() if self.ready else None,
        }

    def save(self, path, signature):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.with_suffix(".tmp").open("wb") as output:
            np.savez(output, mean=self.mean, m2=self.m2, count=self.count, signature=signature)
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
            self.ready = self.count >= 2
            self.progress = 1.0 if self.ready else 0.0
            self.saved = self.ready
            return self.ready
        except (OSError, ValueError, KeyError, EOFError, BadZipFile):
            return False
