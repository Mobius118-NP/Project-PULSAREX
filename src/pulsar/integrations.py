"""Independent, bounded evidence adapters. Visual identity data is not accepted."""
from collections import deque
from datetime import UTC, datetime
from threading import RLock

from pydantic import BaseModel, ConfigDict, Field, field_validator


class VisualObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    schema_version: int = Field(default=1, ge=1, le=1)
    observation_id: str = Field(min_length=1, max_length=96)
    timestamp: datetime
    camera_id: str = Field(min_length=1, max_length=96)
    fov_center_deg: float = Field(ge=0, lt=360)
    fov_width_deg: float = Field(gt=0, le=360)
    clock_uncertainty_ms: float = Field(ge=0, le=10000)
    description: str = Field(default="Visual observation", max_length=256)

    @field_validator("timestamp")
    @classmethod
    def aware_timestamp(cls, value):
        if value.tzinfo is None:
            raise ValueError("Timestamp must include timezone; synchronize sensor clocks")
        if abs((datetime.now(UTC)-value).total_seconds()) > 60:
            raise ValueError("Observation must be within 60 seconds of server time")
        return value


class IntegrationHub:
    def __init__(self):
        self.visual = deque(maxlen=256)
        self.lock = RLock()

    def add_visual(self, observation):
        payload = observation.model_dump(mode="json")
        with self.lock:
            self.visual.append(payload)
        return payload

    def snapshot(self, enabled, acoustic_timestamp=None):
        with self.lock:
            recent = [dict(v) for v in self.visual if
                      (datetime.now(UTC)-datetime.fromisoformat(v["timestamp"])).total_seconds() <= 60]
        associations = []
        if enabled and acoustic_timestamp:
            stamp = datetime.fromisoformat(acoustic_timestamp)
            for visual in recent:
                difference = abs((stamp-datetime.fromisoformat(visual["timestamp"])).total_seconds())
                tolerance = .1+visual["clock_uncertainty_ms"]/1000
                if difference <= tolerance:
                    associations.append({"observation_id": visual["observation_id"],
                                         "time_difference_seconds": round(difference, 4),
                                         "uncertainty_seconds": tolerance,
                                         "causal_attribution": False})
        return {"argos_enabled": enabled, "visual_observations": recent if enabled else [],
                "temporal_associations": associations,
                "status": "receiving" if enabled and recent else "awaiting ARGOS" if enabled else "disabled",
                "clock_guidance": "Use synchronized UTC clocks; associations are temporal only"}


def vibration_features(samples, sample_rate):
    """External sensor research adapter; separate units and no acoustic source inference."""
    import numpy as np

    values = np.asarray(samples, dtype=float)
    if values.ndim != 1 or not 16 <= len(values) <= 65536 or not np.isfinite(values).all():
        raise ValueError("Expected 16-65536 finite external sensor samples")
    if not 0 < sample_rate <= 192000:
        raise ValueError("Invalid external sensor sample rate")
    transform = np.abs(np.fft.rfft((values-values.mean())*np.hanning(len(values))))
    return {"rms_sensor_units": float(np.sqrt(np.mean(values**2))),
            "peak_hz": float(np.fft.rfftfreq(len(values), 1/sample_rate)[transform.argmax()]),
            "sensor_type": "vibration", "acoustic_measurement": False}
