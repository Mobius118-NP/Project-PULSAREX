"""Bounded acquisition. The PortAudio callback copies only; no DSP or I/O."""

import sys
import time
from queue import Empty, Full, Queue

import numpy as np


def devices():
    try:
        import sounddevice as sd

        apis = sd.query_hostapis()
        return [
            {
                "id": i,
                "name": d["name"],
                "backend": apis[d["hostapi"]]["name"],
                "channels": d["max_input_channels"],
                "default_sample_rate": d["default_samplerate"],
            }
            for i, d in enumerate(sd.query_devices())
            if d["max_input_channels"] > 0
        ]
    except Exception as exc:
        raise RuntimeError(f"Audio devices unavailable: {exc}") from exc


class SyntheticSource:
    """Deterministic harmonic tone, slow shift, and periodic broadband events.

    Generates data only; nothing is played through speakers.
    """

    def __init__(self, config):
        self.config = config
        self.samples = 0
        self.phase = 0.0
        self.rng = np.random.default_rng(42)

    def read(self):
        cfg = self.config
        t = (np.arange(cfg.hop_size) + self.samples) / cfg.sample_rate
        freq = cfg.reference_hz + min(0.65 * cfg.shift_range_hz, cfg.reference_hz * 0.25) * np.sin(t * 0.32)
        phase = self.phase + np.cumsum(2 * np.pi * freq / cfg.sample_rate)
        self.phase = float(phase[-1] % (2 * np.pi))
        signal = 0.24 * np.sin(phase)
        for harmonic, level in ((2, 0.10), (3, 0.05), (4, 0.025)):
            if harmonic * float(freq.max()) < cfg.sample_rate / 2:
                signal += level * np.sin(harmonic * phase)
        transient = (t % 14 > 10) & (t % 14 < 10.35)
        signal += self.rng.normal(0, 0.002, cfg.hop_size)
        signal += self.rng.normal(0, 0.08, cfg.hop_size) * transient
        self.samples += cfg.hop_size
        return np.repeat(signal[:, None], cfg.channels, axis=1).astype(np.float32)


class MicrophoneSource:
    def __init__(self, config):
        self.config = config
        self.queue = Queue(maxsize=8)
        self.overruns = 0
        self.last_timestamp = None
        self.stream = None

    def _callback(self, indata, frames, timing, status):
        if status.input_overflow:
            self.overruns += 1
        try:
            self.queue.put_nowait((indata.copy(), time.time()))
        except Full:
            self.overruns += 1

    def start(self):
        import sounddevice as sd

        device = self.config.device
        if device is None and sys.platform == "win32":
            for api in sd.query_hostapis():
                if api["name"] == "Windows WASAPI" and api["default_input_device"] >= 0:
                    device = api["default_input_device"]
                    break
        sd.check_input_settings(
            device=device, channels=self.config.channels, dtype="float32", samplerate=self.config.sample_rate
        )
        self.stream = sd.InputStream(
            samplerate=self.config.sample_rate,
            blocksize=self.config.hop_size,
            channels=self.config.channels,
            device=device,
            dtype="float32",
            callback=self._callback,
        )
        self.stream.start()

    def read(self):
        try:
            data, self.last_timestamp = self.queue.get(timeout=0.5)
            return data
        except Empty as exc:
            raise RuntimeError("No microphone frames. Check connection and input permissions.") from exc

    def close(self):
        if self.stream is not None:
            try:
                self.stream.stop()
            finally:
                self.stream.close()
