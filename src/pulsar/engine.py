import sqlite3
import time
from collections import deque
from dataclasses import replace
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path
from threading import Event, RLock, Thread
from uuid import uuid4

import numpy as np

from .audio import ManagedMicrophoneSource as MicrophoneSource
from .audio import SyntheticSource
from .baseline import Baseline, Profiles
from .direction import direction_measurement
from .dsp import Analyzer
from .events import characterize
from .storage import EventDetector, EventStore, EventWriter


def serialized(method):
    """Serialize controls without holding the worker's snapshot lock while joining."""

    @wraps(method)
    def call(self, *args, **kwargs):
        with self.control_lock:
            return method(self, *args, **kwargs)

    return call


class Engine:
    def __init__(self, config):
        self.config = config.validate()
        self.lock = RLock()
        self.control_lock = RLock()
        self.stop_event = Event()
        self.thread = None
        self.capture = False
        self.error = None
        self.latest = None
        self.sequence = 0
        self.overruns = 0
        self.clients = 0
        self.source_active = False
        self.last_sample_at = None
        self.input_info = {}
        self.warnings = {}
        self.config_revision = 0
        self.band_ceiling = config.max_frequency
        self.last_save_attempt = 0.0
        self.profile_id = "default"
        self.profiles = Profiles(Path(config.data_dir) / "profiles")
        self.known_state = None
        self.profile_cache = {}
        self.shift_history = deque(maxlen=240)
        self.bearing_history = deque(maxlen=120)
        try:
            self.store = EventStore(Path(config.data_dir) / "events.sqlite3")
        except (OSError, sqlite3.Error) as exc:
            self.store = EventStore(":memory:")
            self.warnings["storage"] = f"Persistent event storage unavailable; events are temporary: {exc}"
        self._reset_pipeline()
        self.writer = EventWriter(self.store, self.warnings)

    def _reset_continuity(self, preserve_latest=False):
        self._interrupt_event("Stream continuity lost; ending time unknown")
        self.stream_id = uuid4().hex
        self.analyzer.previous = None
        self.analyzer.smoothed = None
        self.analyzer.previous_fundamentals = []
        self.detector.reset()
        self.baseline.pause()
        self.shift_history.clear()
        self.bearing_history.clear()
        if not preserve_latest:
            self.latest = None
            self.last_sample_at = None

    def _interrupt_event(self, reason):
        if self.detector.active and hasattr(self, "writer"):
            self.writer.submit({**self.detector.active, "state": "interrupted", "uncertainty": reason})
        self.detector.reset()

    def _save_baseline(self, force=False):
        now = time.monotonic()
        if not self.baseline.ready or not self.baseline.dirty:
            return
        interval = 30 if self.baseline.saved else 3
        if not force and now - self.last_save_attempt < interval:
            return
        self.last_save_attempt = now
        try:
            self.baseline.save(self.baseline_path, self._signature())
            self.warnings.pop("baseline", None)
        except OSError as exc:
            self.warnings["baseline"] = f"Baseline persistence unavailable: {exc}"

    def _signature(self):
        c = self.config
        return repr(
            (
                c.sample_rate,
                c.fft_size,
                c.min_frequency,
                c.max_frequency,
                c.display_bins,
                c.source,
                c.device,
                c.channels,
            )
        )

    def _reset_pipeline(self):
        self.analyzer = Analyzer(self.config)
        self.baseline = Baseline(self.config.fft_size // 2 + 1, self.config.calibration_seconds,
                                 self.config.adaptation_seconds, self.config.sensitivity)
        self.baseline_path = Path(self.config.data_dir) / "baseline-v3.npz"
        self.baseline.load(self.baseline_path, self._signature())
        self.detector = EventDetector(self.config.event_threshold_db, self.config.event_cooldown_seconds)
        self.last_save_attempt = 0.0
        self._reset_continuity()
        self._cache_profiles()

    def _cache_profiles(self):
        self.profile_cache.clear()
        for name in self.profiles.names():
            try:
                candidate = self.profiles.load(name, self.baseline.bins, self.baseline.duration, self._signature())
                self.profile_cache[name] = (candidate.mean, candidate.scale)
            except ValueError:
                continue

    @serialized
    def profile(self, action, name="default"):
        with self.lock:
            if action == "save":
                self.profiles.save(name, self.baseline, self._signature())
                self.profile_id = name
                self._cache_profiles()
            elif action == "load":
                self._interrupt_event("Baseline profile changed; ending time unknown")
                self.baseline = self.profiles.load(name, self.baseline.bins, self.baseline.duration, self._signature())
                self.baseline.adaptation_seconds = self.config.adaptation_seconds
                self.baseline.sensitivity = self.config.sensitivity
                self.baseline.dirty = True
                self.profile_id = name
                self.detector.reset()
                self._save_baseline(force=True)
            elif action == "freeze":
                self.baseline.frozen = True
                self.baseline.dirty = self.baseline.ready
            elif action == "unfreeze":
                self.baseline.frozen = False
                self.baseline.dirty = self.baseline.ready
            elif action == "reset":
                self._interrupt_event("Baseline reset; ending time unknown")
                self.baseline.calibrate(time.monotonic())
                self.detector.reset()
            else:
                raise ValueError("Unknown baseline action")
            return self.baseline.status()

    @serialized
    def start(self):
        with self.lock:
            if self.thread and self.thread.is_alive():
                return
            self.capture = True
            self.error = None
            self.source_active = False
            self._reset_continuity()
            self.stop_event.clear()
            self.thread = Thread(target=self._run, name="pulsar-acquisition", daemon=True)
            self.thread.start()

    @serialized
    def stop(self):
        with self.lock:
            self.capture = False
            self.stop_event.set()
        thread = self.thread
        if thread and thread.is_alive():
            thread.join(timeout=4)
            if thread.is_alive():
                raise RuntimeError("Acquisition is still stopping; retry shortly")
        with self.lock:
            self.source_active = False
            if self.detector.active:
                event = {**self.detector.active, "state": "interrupted",
                         "uncertainty": "Capture stopped while deviation was active; ending time unknown"}
                self.writer.submit(event)
                self.detector.reset()
            self.baseline.pause()
            self._save_baseline(force=True)

    @serialized
    def close(self):
        self.stop()
        self.writer.close()
        self.store.close()

    @serialized
    def configure(self, changes):
        mutable = {
            "source",
            "device",
            "channels",
            "sample_rate",
            "fft_size",
            "hop_size",
            "reference_hz",
            "shift_range_hz",
            "zero_tolerance_hz",
            "calibration_seconds",
            "event_threshold_db",
            "event_cooldown_seconds",
            "harmonics_enabled",
            "baseline_adaptation",
            "mic_positions",
            "min_frequency",
            "max_frequency",
            "adaptation_seconds", "sensitivity", "band_edges", "auto_calibrate",
            "stereo_synchronized", "stereo_spacing_m", "stereo_axis_deg", "characterization_enabled", "argos_enabled",
        }
        if set(changes) - mutable:
            raise ValueError("Unsupported configuration field")
        updated = replace(self.config, **changes)
        if "mic_positions" not in changes and (
            updated.device != self.config.device or updated.channels != self.config.channels
        ):
            updated.mic_positions = []
        if "stereo_synchronized" not in changes and (
            updated.device != self.config.device or updated.channels != self.config.channels
        ):
            updated.stereo_synchronized = False
        ceiling = changes.get("max_frequency", self.band_ceiling)
        updated.max_frequency = min(ceiling, updated.sample_rate / 2)
        updated.validate()
        actual = {key for key in mutable if getattr(updated, key) != getattr(self.config, key)}
        if not actual:
            self.band_ceiling = ceiling
            return
        live = {
            "reference_hz",
            "shift_range_hz",
            "zero_tolerance_hz",
            "calibration_seconds",
            "event_threshold_db",
            "event_cooldown_seconds",
            "harmonics_enabled",
            "baseline_adaptation",
            "adaptation_seconds", "sensitivity", "characterization_enabled", "argos_enabled",
            "stereo_synchronized", "stereo_spacing_m", "stereo_axis_deg",
        }
        if actual <= live:
            with self.lock:
                self.config = updated
                self.analyzer.config = updated
                self.baseline.duration = updated.calibration_seconds
                self.baseline.adaptation_seconds = updated.adaptation_seconds
                self.baseline.sensitivity = updated.sensitivity
                self.detector.threshold = updated.event_threshold_db
                self.detector.cooldown = updated.event_cooldown_seconds
                self.config_revision += 1
                if actual & {"stereo_synchronized", "stereo_spacing_m", "stereo_axis_deg"}:
                    self.bearing_history.clear()
                    if self.latest:
                        self.latest = {**self.latest,
                                       "direction": {"available": False, "reason": "Updating two-microphone settings"},
                                       "stereo": {"available": False, "reason": "Updating two-microphone settings"}}
                if actual & {"reference_hz", "shift_range_hz", "zero_tolerance_hz"}:
                    self.shift_history.clear()
                    if self.latest:
                        self.latest = {
                            **self.latest,
                            "shift": {
                                **self.latest["shift"],
                                "reliable": False,
                                "status": "updating",
                                "color": "#697585",
                            },
                        }
            return
        was_running = self.capture
        self.stop()
        with self.lock:
            self.config = updated
            self.band_ceiling = ceiling
            self.config_revision += 1
            self.input_info = {}
            self._reset_pipeline()
        if was_running:
            self.start()

    @serialized
    def calibrate(self):
        with self.lock:
            if not self.capture or not self.source_active or self.error:
                raise ValueError("Wait for a healthy acquisition stream before calibration")
            self.baseline.calibrate(time.monotonic())
            self._interrupt_event("Baseline recalibration started; ending time unknown")
            self.detector.reset()

    def snapshot(self):
        with self.lock:
            baseline_status = self.baseline.status()
            if self.baseline.ready:
                baseline_status["mean_dbfs"] = self._display(self.baseline.mean)
                baseline_status["variation_db"] = self._display(self.baseline.scale)
            baseline_status["profile_id"] = self.profile_id
            frame = dict(self.latest) if self.latest else {}
            age = max(0.0, time.monotonic() - self.last_sample_at) if self.last_sample_at else None
            if age is not None and frame.get("captured_at") is not None:
                age = max(age, time.time() - frame["captured_at"])
            fresh = bool(
                self.capture
                and self.source_active
                and not self.error
                and age is not None
                and age <= max(1.0, 3 * self.config.hop_size / self.config.sample_rate)
            )
            if frame and not fresh:
                frame["shift"] = {**frame["shift"], "reliable": False, "status": "stale", "color": "#697585"}
                frame["direction"] = {"available": False, "reason": "No current acquisition data"}
                frame["stereo"] = {"available": False, "reason": "No current acquisition data"}
            return {
                "type": "measurement",
                "schema_version": 1,
                "sequence": self.sequence,
                "stream_id": self.stream_id,
                "config_revision": self.config_revision,
                "config": self.config.public(),
                "measurement_valid": fresh,
                "sample_age_seconds": round(age, 3) if age is not None else None,
                **frame,
                "status": {
                    "running": self.capture,
                    "source": self.config.source,
                    "microphone_active": self.capture
                    and self.source_active
                    and self.config.source == "microphone"
                    and not self.error,
                    "source_active": self.source_active,
                    "error": self.error,
                    "sample_rate": self.config.sample_rate,
                    "channels": self.config.channels,
                    "device": self.config.device,
                    "overruns": self.overruns,
                    "clients": self.clients,
                    "fft_size": self.config.fft_size,
                    "hop_size": self.config.hop_size,
                    "input": dict(self.input_info),
                    "warnings": list(self.warnings.copy().values()),
                    "pending_event_writes": self.writer.queue.qsize(),
                    "dropped_event_updates": self.writer.dropped,
                },
                "baseline": baseline_status,
                "active_anomaly": self.detector.active if fresh else None,
                "known_state": self.known_state,
                "shift_history": list(self.shift_history),
                "bearing_history": list(self.bearing_history),
            }

    def _display(self, values):
        return [round(float(np.max(values[a:b])), 2) if a < b else -140
                for a, b in self.analyzer.bin_ranges]

    def _run(self):
        cfg = self.config
        source = None
        buffer = np.zeros((cfg.fft_size, cfg.channels), dtype=np.float32)
        filled = 0
        retry_at = 0
        next_publish = 0
        previous_overruns = 0
        previous_sample_sequence = None
        try:
            while not self.stop_event.is_set():
                cfg = self.config
                if source is None:
                    if self.stop_event.wait(max(0, retry_at - time.monotonic())):
                        break
                    try:
                        source = SyntheticSource(cfg) if cfg.source == "simulation" else MicrophoneSource(cfg)
                        if isinstance(source, MicrophoneSource):
                            source.start(self.stop_event)
                        with self.lock:
                            self._reset_continuity()
                            self.error = None
                            self.source_active = True
                            self.input_info = {
                                "device": getattr(source, "device_id", None),
                                "name": getattr(source, "device_name", "Synthetic generator"),
                                "backend": getattr(source, "backend", "simulation"),
                            }
                        filled = 0
                        buffer.fill(0)
                        previous_overruns = 0
                        previous_sample_sequence = None
                    except Exception as exc:
                        if self.stop_event.is_set():
                            break
                        self.error = (
                            f"Input unavailable: {exc}. Check the selected backend/native sample rate, "
                            "Windows microphone access for desktop apps, and whether another app holds "
                            "the device exclusively. Retrying in 3 seconds."
                        )
                        if isinstance(source, MicrophoneSource):
                            try:
                                source.close()
                            except Exception:
                                pass
                        source = None
                        self.source_active = False
                        retry_at = time.monotonic() + 3
                        continue
                started = time.monotonic()
                try:
                    source.config = cfg
                    block = (
                        source.read(self.stop_event)
                        if isinstance(source, MicrophoneSource)
                        else source.read()
                    )
                except Exception as exc:
                    if self.stop_event.is_set():
                        break
                    self.error = f"Capture interrupted: {exc}. Retrying in 3 seconds."
                    with self.lock:
                        self.source_active = False
                        self._reset_continuity(preserve_latest=True)
                    if isinstance(source, MicrophoneSource):
                        try:
                            source.close()
                        except Exception:
                            pass
                    source = None
                    retry_at = time.monotonic() + 3
                    continue
                current_overruns = getattr(source, "overruns", 0)
                sample_sequence = getattr(source, "last_sequence", None)
                discontinuity = (
                    sample_sequence is not None
                    and previous_sample_sequence is not None
                    and sample_sequence != previous_sample_sequence + len(block)
                )
                if current_overruns != previous_overruns or discontinuity:
                    with self.lock:
                        self.overruns += current_overruns - previous_overruns
                        self._reset_continuity()
                    buffer.fill(0)
                    filled = 0
                    previous_overruns = current_overruns
                previous_sample_sequence = sample_sequence
                size = len(block)
                if size >= cfg.fft_size:
                    buffer[:] = block[-cfg.fft_size :]
                else:
                    buffer[:-size] = buffer[size:]
                    buffer[-size:] = block
                filled += size
                now = time.monotonic()
                if filled >= cfg.fft_size:
                    processing_started = time.perf_counter()
                    frame = self.analyzer.analyze(buffer)
                    stamp = datetime.now(UTC).isoformat()
                    frame.update(
                        timestamp=stamp,
                        source=cfg.source,
                        captured_at=getattr(source, "last_timestamp", None),
                    )
                    with self.lock:
                        if cfg.auto_calibrate and not self.baseline.ready and not self.baseline.calibrating:
                            self.baseline.calibrate(now)
                        deviation = self.baseline.update(
                            frame["_linear_dbfs"], now,
                            cfg.baseline_adaptation and not self.baseline.frozen, cfg.event_threshold_db
                        )
                        self._save_baseline()
                        event = self.detector.detect(frame, deviation, self.baseline.ready, now, stamp,
                                                     self.baseline.scale, cfg.sensitivity,
                                                     self.profile_id, cfg.sensor_id, cfg.band_edges)
                        if event and cfg.characterization_enabled:
                            event["characterization"] = characterize(frame)
                    if event:
                        self.writer.submit(event)
                    if now >= next_publish:
                        self.known_state = None
                        values = np.asarray(frame["_linear_dbfs"])
                        for name, (mean, scale) in self.profile_cache.items():
                            relevant = ((np.maximum(mean, values) > -90) &
                                        (self.analyzer.freq >= cfg.min_frequency) &
                                        (self.analyzer.freq <= cfg.max_frequency))
                            if not np.any(relevant & (np.abs(values-mean) >= cfg.event_threshold_db)
                                          & (np.abs(values-mean)/scale >= cfg.sensitivity)):
                                self.known_state = name
                                break
                        direction, frame["stereo"] = direction_measurement(buffer, cfg, now)
                        frame.update(
                            direction=direction,
                            deviation_db=(np.asarray(frame["spectrum_dbfs"])-np.asarray(self._display(self.baseline.mean))).round(2).tolist()
                            if self.baseline.ready else [0.0]*cfg.display_bins,
                            processing_ms=round((time.perf_counter() - processing_started) * 1000, 2),
                        )
                        frame.pop("_linear_dbfs", None)
                        frame.pop("_linear_frequencies", None)
                        with self.lock:
                            if cfg is not self.config:
                                continue  # Never publish a frame computed for superseded live settings.
                            self.sequence += 1
                            self.latest = frame
                            self.last_sample_at = time.monotonic()
                            self.shift_history.append({"timestamp": stamp, **frame["shift"]})
                            if direction.get("available"):
                                self.bearing_history.append({"timestamp": stamp, **direction})
                        next_publish = now + 1 / cfg.update_hz
                if cfg.source == "simulation":
                    self.stop_event.wait(
                        max(0, cfg.hop_size / cfg.sample_rate - (time.monotonic() - started))
                    )
        except Exception as exc:
            self.error = f"Processing stopped: {exc}"
        finally:
            if isinstance(source, MicrophoneSource):
                try:
                    source.close()
                except Exception:
                    pass
            self.capture = False
            self.source_active = False
