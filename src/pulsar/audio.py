"""Bounded acquisition. The PortAudio callback copies only; no DSP or I/O."""

import multiprocessing as mp
import sys
import time
from queue import Empty, Full, Queue

import numpy as np


def automatic_input(sd):
    device = sd.default.device[0]
    if sys.platform == "win32":
        for api in sd.query_hostapis():
            if api["name"] == "Windows WASAPI" and api["default_input_device"] >= 0:
                return api["default_input_device"]
    return device


def input_inventory():
    listed = devices()
    try:
        import sounddevice as sd

        default = automatic_input(sd)
    except Exception:
        default = None
    return {
        "devices": listed,
        "default_input": next((d for d in listed if d["id"] == default), None),
        "error": None,
    }


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
        excursion = min(
            0.65 * cfg.shift_range_hz,
            cfg.reference_hz * 0.25,
            0.95 * (cfg.sample_rate / 2 - cfg.reference_hz),
            0.95 * (cfg.reference_hz - 20),
        )
        freq = cfg.reference_hz + excursion * np.sin(t * 0.32)
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
        self.device_id = None
        self.device_name = None
        self.backend = None
        self.sample_count = 0
        self.last_sequence = None

    def _callback(self, indata, frames, timing, status):
        self.sample_count += frames
        packet = (indata.copy(), time.time(), self.sample_count)
        if status.input_overflow:
            self.overruns += 1
        try:
            self.queue.put_nowait(packet)
        except Full:
            self.overruns += 1
            # Keep the newest audio rather than letting an old queue become a delay line.
            try:
                self.queue.get_nowait()
            except Empty:
                pass
            try:
                self.queue.put_nowait(packet)
            except Full:
                pass

    def start(self):
        import sounddevice as sd

        device = self.config.device
        if device is None:
            device = automatic_input(sd)
        sd.check_input_settings(
            device=device, channels=self.config.channels, dtype="float32", samplerate=self.config.sample_rate
        )
        info = sd.query_devices(device, "input")
        self.device_id = info["index"]
        self.device_name = info["name"]
        self.backend = sd.query_hostapis(info["hostapi"])["name"]
        self.stream = sd.InputStream(
            samplerate=self.config.sample_rate,
            blocksize=self.config.hop_size,
            channels=self.config.channels,
            device=device,
            dtype="float32",
            callback=self._callback,
        )
        self.stream.start()

    def read(self, stop_event=None):
        deadline = time.monotonic() + max(0.5, 3 * self.config.hop_size / self.config.sample_rate)
        while stop_event is None or not stop_event.is_set():
            try:
                data, self.last_timestamp, self.last_sequence = self.queue.get(timeout=0.1)
                return data
            except Empty:
                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        "No microphone frames. Check connection and input permissions."
                    ) from None
        raise InterruptedError("Capture stopped")

    def close(self):
        if self.stream is not None:
            try:
                self.stream.stop()
            finally:
                self.stream.close()


def _capture_process(config, frames, messages, stopped):
    """Keep native driver calls outside the server and DSP process."""
    source = MicrophoneSource(config)
    relay_drops = 0
    try:
        source.start()
        messages.send(
            {"ready": True, "device": source.device_id, "name": source.device_name, "backend": source.backend}
        )
        while not stopped.is_set():
            data = source.read(stopped)
            packet = (data, source.last_timestamp, source.overruns + relay_drops, source.last_sequence)
            try:
                frames.put_nowait(packet)
            except Full:
                relay_drops += 1
                packet = (data, source.last_timestamp, source.overruns + relay_drops, source.last_sequence)
                try:
                    frames.get_nowait()
                except Empty:
                    pass
                try:
                    frames.put_nowait(packet)
                except Full:
                    pass
    except InterruptedError:
        pass
    except Exception as exc:
        try:
            messages.send({"error": str(exc)})
        except (BrokenPipeError, OSError):
            pass
    finally:
        try:
            source.close()
        finally:
            frames.cancel_join_thread()
            messages.close()


class ManagedMicrophoneSource:
    """Bounded, cancellable microphone capture with a terminable driver process."""

    startup_timeout = 6.0

    def __init__(self, config):
        self.config = config
        self.context = mp.get_context("spawn")
        self.frames = self.context.Queue(maxsize=8)
        self.messages, self.sender = self.context.Pipe(duplex=False)
        self.stopped = self.context.Event()
        self.process = None
        self.last_timestamp = None
        self.overruns = 0
        self.device_id = None
        self.device_name = None
        self.backend = None
        self.last_sequence = None

    def start(self, stop_event=None):
        self.process = self.context.Process(
            target=_capture_process,
            args=(self.config, self.frames, self.sender, self.stopped),
            name="pulsar-microphone",
            daemon=True,
        )
        self.process.start()
        self.sender.close()
        deadline = time.monotonic() + self.startup_timeout
        while time.monotonic() < deadline:
            if stop_event is not None and stop_event.is_set():
                raise InterruptedError("Capture stopped")
            if self.messages.poll(0.1):
                try:
                    result = self.messages.recv()
                except EOFError as exc:
                    raise RuntimeError("Microphone driver exited during startup") from exc
                if result.get("error"):
                    raise RuntimeError(result["error"])
                self.device_id = result["device"]
                self.device_name = result["name"]
                self.backend = result["backend"]
                return
            if not self.process.is_alive():
                raise RuntimeError("Microphone driver exited during startup")
        raise RuntimeError(
            f"Microphone driver did not respond within {self.startup_timeout:g} seconds; choose another input"
        )

    def read(self, stop_event=None):
        deadline = time.monotonic() + max(1.0, 3 * self.config.hop_size / self.config.sample_rate)
        while stop_event is None or not stop_event.is_set():
            if self.messages.poll():
                try:
                    message = self.messages.recv()
                except EOFError:
                    message = {"error": "Microphone driver disconnected"}
                if message.get("error"):
                    raise RuntimeError(message["error"])
            try:
                data, self.last_timestamp, self.overruns, self.last_sequence = self.frames.get(timeout=0.1)
                return data
            except Empty:
                if not self.process.is_alive():
                    raise RuntimeError("Microphone driver disconnected") from None
                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        "No microphone samples arrived; choose another input or retry"
                    ) from None
        raise InterruptedError("Capture stopped")

    def close(self):
        self.stopped.set()
        if self.process is not None and self.process.pid is not None:
            self.process.join(timeout=0.5)
            if self.process.is_alive():
                self.process.terminate()
                self.process.join(timeout=1)
            if self.process.is_alive():
                self.process.kill()
                self.process.join(timeout=1)
        self.messages.close()
        self.sender.close()
        self.frames.close()
        self.frames.cancel_join_thread()
