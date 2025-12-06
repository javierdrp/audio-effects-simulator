from __future__ import annotations
import numpy as np
import numba
import audioblocks as ab

@numba.njit(cache=True, fastmath=True)
def gate_kernel(x_in, x_out, gain_state, thresh_lin, attack_coeff, release_coeff):
    """
    x_in: (frames, channels)
    x_out: (frames, channels)
    gain_state: float (current gain value 0.0 to 1.0)
    """
    frames = x_in.shape[0]
    channels = x_in.shape[1]
    
    current_gain = gain_state

    for i in range(frames):
        # 1. Detect input level (Max absolute value across channels for stereo linking)
        #    (If L is loud but R is quiet, we still want to open the gate for both)
        input_lvl = 0.0
        for c in range(channels):
            abs_val = abs(x_in[i, c])
            if abs_val > input_lvl:
                input_lvl = abs_val
        
        # 2. Determine target gain
        target = 1.0 if input_lvl > thresh_lin else 0.0
        
        # 3. Smooth the gain (Attack/Release)
        #    If we are below target, we are attacking (opening). 
        #    If we are above target, we are releasing (closing).
        if current_gain < target:
            current_gain = (1.0 - attack_coeff) * current_gain + attack_coeff * target
        else:
            current_gain = (1.0 - release_coeff) * current_gain + release_coeff * target
            
        # 4. Apply gain to all channels
        for c in range(channels):
            x_out[i, c] = x_in[i, c] * current_gain

    return current_gain


class NoiseGateEffect(ab.Effect):
    def __init__(self, threshold_db=-40.0, attack_ms=10.0, release_ms=100.0):
        # Parameters
        self.threshold_db = ab.SmoothParam(threshold_db, -80.0, 0.0)
        self.attack_ms = ab.SmoothParam(attack_ms, 1.0, 500.0)
        self.release_ms = ab.SmoothParam(release_ms, 10.0, 1000.0)

        # State
        self._gain_state = 0.0  # Start closed (or open? 0.0 is safer to prevent initial blast if noisy)
        self._fs = 48000.0

    def set_threshold_db(self, v): self.threshold_db.set_target(v)
    def set_attack_ms(self, v): self.attack_ms.set_target(v)
    def set_release_ms(self, v): self.release_ms.set_target(v)

    def prepare(self, sample_rate: int, channels_in: int, channels_out: int, blocksize: int):
        self._fs = float(sample_rate)

    def _calc_coeff(self, time_ms):
        # 1-pole lowpass coefficient: coeff = 1 - exp(-1 / (tau * fs))
        # This is a rough approximation suitable for gain smoothing
        # To make it intuitively "reach target in X ms", we can use a simplified linear step logic
        # or a standard exponential approach. Let's use standard exponential decay logic.
        t = max(1e-3, time_ms * 1e-3)
        return 1.0 - np.exp(-2.2 / (t * self._fs)) # 2.2 factor makes it reach ~90% in time_ms

    def process_into(self, x_in: np.ndarray, out: np.ndarray) -> None:
        # 1. Update params
        th_db = self.threshold_db.step_towards(1.0)
        att_ms = self.attack_ms.step_towards(5.0)
        rel_ms = self.release_ms.step_towards(10.0)

        # 2. Pre-calculate constants for this block
        thresh_lin = 10.0 ** (th_db / 20.0)
        att_coeff = self._calc_coeff(att_ms)
        rel_coeff = self._calc_coeff(rel_ms)

        # 3. Run kernel
        self._gain_state = gate_kernel(
            x_in, 
            out, 
            self._gain_state, 
            thresh_lin, 
            att_coeff, 
            rel_coeff
        )
