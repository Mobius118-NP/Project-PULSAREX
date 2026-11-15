import time
from collections import deque
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, RLock, Thread

import numpy as np

from .audio import MicrophoneSource, SyntheticSource
from .baseline import Baseline
from .dsp import Analyzer, estimate_bearing
from .storage import EventDetector, EventStore


class Engine:
    def __init__(self, config):
        self.config = config.validate()
        self.lock = RLock()
        self.stop_event = Event()
        self.thread = None
        self.capture = False
        self.error = None
        self.latest = None
        self.sequence = 0
        self.overruns = 0
        self.clients = 0
        self.shift_history = deque(maxlen=240)
        self.bearing_history = deque(maxlen=120)
        self.store = EventStore(Path(config.data_dir) / "events.sqlite3")
        self._reset_pipeline()

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
        self.baseline = Baseline(self.config.display_bins, self.config.calibration_seconds)
        self.baseline_path = Path(self.config.data_dir) / "baseline.npz"
        self.baseline.load(self.baseline_path, self._signature())
        self.detector = EventDetector(self.config.event_threshold_db, self.config.event_cooldown_seconds)
        self.shift_history.clear()
        self.bearing_history.clear()
        self.latest = None

    def start(self):
        with self.lock:
            if self.thread and self.thread.is_alive():
                return
            self.capture = True
            self.error = None
            self.stop_event.clear()
            self.thread = Thread(target=self._run, name="pulsar-acquisition", daemon=True)
            self.thread.start()

    def stop(self):
        self.capture = False
        self.stop_event.set()
        thread = self.thread
        if thread and thread.is_alive():
            thread.join(timeout=4)
            if thread.is_alive():
                raise RuntimeError("Acquisition is still stopping; retry shortly")

    def close(self):
        self.stop()
        self.store.close()

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
        }
        if set(changes) - mutable:
            raise ValueError("Unsupported configuration field")
        updated = replace(self.config, **changes)
        updated.max_frequency = min(updated.max_frequency, updated.sample_rate / 2)
        updated.validate()
        was_running = self.capture
        self.stop()
        with self.lock:
            self.config = updated
            self._reset_pipeline()
        if was_running:
            self.start()

    def calibrate(self):
        with self.lock:
            if not self.capture:
                raise ValueError("Start acquisition before calibration")
            self.baseline.calibrate(time.monotonic())

    def snapshot(self):
        with self.lock:
            frame = dict(self.latest) if self.latest else {}
            return {
                "type": "measurement",
                "schema_version": 1,
                "sequence": self.sequence,
                **frame,
                "status": {
                    "running": self.capture,
                    "source": self.config.source,
                    "microphone_active": self.capture
                    and self.config.source == "microphone"
                    and not self.error,
                    "error": self.error,
                    "sample_rate": self.config.sample_rate,
                    "channels": self.config.channels,
                    "device": self.config.device,
                    "overruns": self.overruns,
                    "clients": self.clients,
                    "fft_size": self.config.fft_size,
                    "hop_size": self.config.hop_size,
                },
                "baseline": self.baseline.status(),
                "shift_history": list(self.shift_history),
                "bearing_history": list(self.bearing_history),
            }

    def _run(self):
        cfg = self.config
        source = None
        buffer = np.zeros((cfg.fft_size, cfg.channels), dtype=np.float32)
        filled = 0
        retry_at = 0
        next_publish = 0
        try:
            while not self.stop_event.is_set():
                if source is None:
                    if self.stop_event.wait(max(0, retry_at - time.monotonic())):
                        break
                    try:
                        source = SyntheticSource(cfg) if cfg.source == "simulation" else MicrophoneSource(cfg)
                        if isinstance(source, MicrophoneSource):
                            source.start()
                        self.error = None
                    except Exception as exc:
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
                        retry_at = time.monotonic() + 3
                        continue
                started = time.monotonic()
                try:
                    block = source.read()
                except Exception as exc:
                    self.error = f"Capture interrupted: {exc}. Retrying in 3 seconds."
                    if isinstance(source, MicrophoneSource):
                        try:
                            source.close()
                        except Exception:
                            pass
                    source = None
                    retry_at = time.monotonic() + 3
                    continue
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
                        deviation = self.baseline.update(
                            frame["spectrum_dbfs"], now, cfg.baseline_adaptation, cfg.event_threshold_db
                        )
                        if self.baseline.ready and not self.baseline.saved:
                            self.baseline.save(self.baseline_path, self._signature())
                        event = self.detector.detect(frame, deviation, self.baseline.ready, now, stamp)
                    if event:
                        self.store.add(event)
                    if now >= next_publish:
                        # Synthetic direction is deliberately labelled simulation, never live bearing.
                        if cfg.source == "simulation":
                            direction = {
                                "available": True,
                                "simulated": True,
                                "bearing_deg": round((now * 8) % 360, 1),
                                "confidence": 0.85,
                                "uncertainty_deg": 12,
                            }
                        elif cfg.mic_positions:
                            direction = estimate_bearing(buffer, cfg.sample_rate, cfg.mic_positions)
                        else:
                            direction = {
                                "available": False,
                                "reason": "Synchronized calibrated array required",
                            }
                        frame.update(
                            direction=direction,
                            deviation_db=deviation.round(2).tolist(),
                            processing_ms=round((time.perf_counter() - processing_started) * 1000, 2),
                        )
                        with self.lock:
                            self.sequence += 1
                            self.latest = frame
                            self.shift_history.append({"timestamp": stamp, **frame["shift"]})
                            if direction.get("available"):
                                self.bearing_history.append({"timestamp": stamp, **direction})
                        next_publish = now + 1 / cfg.update_hz
                self.overruns = getattr(source, "overruns", 0)
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
