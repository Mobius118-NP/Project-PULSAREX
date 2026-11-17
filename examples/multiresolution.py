"""Compare low-frequency resolution and transient timing without modifying live measurements."""
import json

import numpy as np
from scipy.signal import stft


def compare():
    rate = 48000
    t = np.arange(rate*2)/rate
    signal = .1*np.sin(2*np.pi*60*t)+.1*np.sin(2*np.pi*70*t)
    signal[rate] += 1
    result = {}
    for size in (1024, 4096, 16384):
        frequencies, times, spectrum = stft(signal, rate, window='hann', nperseg=size,
                                           noverlap=size-256, boundary=None, padded=False)
        result[size] = {'frequency_resolution_hz': rate/size, 'window_ms': size/rate*1000,
                        'frames': len(times), 'bins': len(frequencies),
                        'peak_magnitude': float(np.abs(spectrum).max())}
    return result


if __name__ == '__main__':
    print(json.dumps(compare(), indent=2))
