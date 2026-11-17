import math
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class Config:
    sample_rate: int = 48000
    fft_size: int = 4096
    hop_size: int = 1024
    channels: int = 1
    source: str = "simulation"
    device: int | None = None
    min_frequency: float = 30.0
    max_frequency: float = 18000.0
    display_bins: int = 384
    update_hz: float = 12.0
    reference_hz: float = 1000.0
    shift_range_hz: float = 200.0
    zero_tolerance_hz: float = 2.0
    calibration_seconds: float = 5.0
    event_threshold_db: float = 12.0
    event_cooldown_seconds: float = 3.0
    harmonics_enabled: bool = True
    baseline_adaptation: bool = False
    auto_calibrate: bool = True
    adaptation_seconds: float = 300.0
    sensitivity: float = 4.0
    band_edges: list[float] = field(default_factory=lambda: [250.0, 4000.0])
    sensor_id: str = "local-acoustic-01"
    stereo_synchronized: bool = False
    stereo_spacing_m: float = 0.1
    stereo_axis_deg: float = 90.0
    argos_enabled: bool = False
    characterization_enabled: bool = False
    mdns_enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8765
    data_dir: str = "data"
    mic_positions: list[list[float]] = field(default_factory=list)

    def validate(self):
        integers = ("sample_rate", "fft_size", "hop_size", "channels", "display_bins", "port")
        for key in integers:
            if type(getattr(self, key)) is not int:
                raise ValueError(f"{key} must be an integer")
        if self.sample_rate not in (8000, 16000, 22050, 44100, 48000, 96000):
            raise ValueError("Unsupported sample rate")
        if self.fft_size < 512 or self.fft_size > 32768 or self.fft_size & (self.fft_size - 1):
            raise ValueError("fft_size must be a power of two between 512 and 32768")
        if not 128 <= self.hop_size <= self.fft_size or not 1 <= self.channels <= 16:
            raise ValueError("Invalid hop size or channel count")
        if self.source not in ("simulation", "microphone"):
            raise ValueError("source must be simulation or microphone")
        bounds = {
            "min_frequency": (10, self.sample_rate / 2 - 1),
            "max_frequency": (11, self.sample_rate / 2),
            "update_hz": (1, 30),
            "display_bins": (64, 1024),
            "reference_hz": (20, self.sample_rate / 2 - 1),
            "shift_range_hz": (1, 5000),
            "zero_tolerance_hz": (0, 1000),
            "calibration_seconds": (1, 120),
            "event_threshold_db": (3, 80),
            "event_cooldown_seconds": (0.2, 120),
            "adaptation_seconds": (10, 86400),
            "sensitivity": (2, 20),
            "stereo_spacing_m": (0.01, 10),
            "stereo_axis_deg": (0, 359.999),
        }
        for key, (low, high) in bounds.items():
            value = getattr(self, key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"{key} must be a finite number")
            if not low <= value <= high:
                raise ValueError(f"{key} must be between {low} and {high}")
        if not 10 <= self.min_frequency < self.max_frequency <= self.sample_rate / 2:
            raise ValueError("Frequency range must be ordered and within Nyquist")
        if self.zero_tolerance_hz >= self.shift_range_hz:
            raise ValueError("Zero tolerance must be smaller than the shift range")
        if not 1 <= self.port <= 65535:
            raise ValueError("Invalid port")
        if self.device is not None and (type(self.device) is not int or self.device < 0):
            raise ValueError("device must be a nonnegative input ID")
        if not isinstance(self.host, str) or not self.host.strip() or any(c.isspace() for c in self.host):
            raise ValueError("host must be an IP address or hostname")
        if not isinstance(self.data_dir, str) or not self.data_dir.strip():
            raise ValueError("data_dir must be a nonempty path")
        for key in ("harmonics_enabled", "baseline_adaptation", "auto_calibrate", "stereo_synchronized",
                    "argos_enabled", "characterization_enabled", "mdns_enabled"):
            if type(getattr(self, key)) is not bool:
                raise ValueError(f"{key} must be boolean")
        if (not isinstance(self.band_edges, list) or len(self.band_edges) != 2
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in self.band_edges)
            or not 10 < self.band_edges[0] < self.band_edges[1] < 48000):
            raise ValueError("band_edges requires two ordered finite frequency boundaries")
        if not isinstance(self.sensor_id, str) or not 1 <= len(self.sensor_id) <= 100:
            raise ValueError("sensor_id must be 1-100 characters")
        if not isinstance(self.mic_positions, list):
            raise ValueError("mic_positions must be a list of [x, y] positions")
        if self.mic_positions:
            import numpy as np

            geometry = np.asarray(self.mic_positions, dtype=float)
            if (
                geometry.shape != (self.channels, 2)
                or self.channels < 2
                or not np.isfinite(geometry).all()
                or len(np.unique(geometry, axis=0)) != self.channels
                or (self.channels >= 3 and np.linalg.matrix_rank(geometry - geometry.mean(axis=0)) < 2)
            ):
                raise ValueError("Direction requires two distinct synchronized microphones, or >=3 non-collinear microphones")
            if self.channels == 2 and not .01 <= float(np.linalg.norm(geometry[1]-geometry[0])) <= 10:
                raise ValueError("Two-microphone geometry spacing must be 0.01-10 metres")
        return self

    def public(self):
        result = asdict(self)
        result.pop("data_dir")
        return result

    @classmethod
    def load(cls, path: str | None = None):
        if path:
            with Path(path).open("rb") as stream:
                return cls(**tomllib.load(stream)).validate()
        return cls().validate()
