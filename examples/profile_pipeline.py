"""Hardware-independent bounded pipeline benchmark; writes no raw audio."""
import argparse
import json
import time
import tracemalloc

import numpy as np

from pulsar.audio import SyntheticSource
from pulsar.baseline import Baseline
from pulsar.config import Config
from pulsar.dsp import Analyzer
from pulsar.events import EventDetector


def run(frames=600, trace=False):
    cfg = Config()
    source, analyzer = SyntheticSource(cfg), Analyzer(cfg)
    baseline = Baseline(cfg.fft_size//2+1, 1)
    detector = EventDetector()
    baseline.calibrate(0)
    buffer = np.zeros((cfg.fft_size, cfg.channels))
    timings = []
    if trace:
        tracemalloc.start()
    warm_memory = 0
    for index in range(frames):
        block = source.read()
        buffer[:-len(block)] = buffer[len(block):]
        buffer[-len(block):] = block
        started = time.perf_counter()
        frame = analyzer.analyze(buffer)
        delta = baseline.update(frame['_linear_dbfs'], index*cfg.hop_size/cfg.sample_rate)
        detector.detect(frame, delta, baseline.ready, index*cfg.hop_size/cfg.sample_rate, 'synthetic', baseline.scale)
        timings.append((time.perf_counter()-started)*1000)
        if trace and index == frames//2:
            warm_memory = tracemalloc.get_traced_memory()[0]
    current, peak = tracemalloc.get_traced_memory() if trace else (0, 0)
    if trace:
        tracemalloc.stop()
    return {'frames': frames, 'median_processing_ms': round(float(np.median(timings)), 3),
            'p95_processing_ms': round(float(np.percentile(timings, 95)), 3),
            'hop_budget_ms': cfg.hop_size/cfg.sample_rate*1000,
            'traced_peak_bytes': peak, 'second_half_traced_growth_bytes': current-warm_memory,
            'allocation_tracing': trace,
            'note': 'Synthetic offline run; allocation tracing adds latency when enabled; not a hardware soak'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--frames', type=int, default=600)
    parser.add_argument('--trace', action='store_true')
    args = parser.parse_args()
    if not 100 <= args.frames <= 10000:
        parser.error('Use 100-10000 frames')
    print(json.dumps(run(args.frames, args.trace), indent=2))
