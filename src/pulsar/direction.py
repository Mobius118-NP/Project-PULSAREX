"""Optional direction orchestration, independent of acquisition and source detection."""
from .dsp import estimate_bearing
from .stereo import pair_geometry, stereo_delay


def direction_measurement(samples, config, now):
    unavailable = {"available": False, "reason": "Two distinct synchronized microphones with known spacing required"}
    stereo = {"available": False, "reason": "Synchronized stereo input required"}
    if config.source == 'simulation':
        angle = round((now*8) % 360, 1) % 360
        direction = {"available": True, "simulated": True, "bearing_deg": angle,
                     "confidence": .85, "uncertainty_deg": 12}
        if config.channels == 2:
            _, axis = pair_geometry(config.stereo_spacing_m, config.stereo_axis_deg, config.mic_positions)
            direction.update(bearing_deg=None, possible_bearings_deg=[angle, round((2*axis-angle) % 360, 1) % 360],
                             mode='two_microphone', ambiguity='Two simulated candidate bearings; front/back unresolved')
            stereo = {"available": False, "reason": "Synthetic UI bearings; no measured stereo delay"}
        return direction, stereo
    if config.channels == 2:
        stereo = stereo_delay(samples, config.sample_rate, config.stereo_spacing_m,
                              config.stereo_synchronized, config.stereo_axis_deg, config.mic_positions)
        return {**stereo, "mode": "two_microphone", "experimental": True}, stereo
    if config.mic_positions:
        return estimate_bearing(samples, config.sample_rate, config.mic_positions), stereo
    return unavailable, stereo
