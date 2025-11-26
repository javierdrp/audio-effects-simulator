from __future__ import annotations
import numpy as np
import numba
import math
import audioblocks as ab

# Direct Form I Biquad Kernel
@numba.njit(cache=True, fastmath=True)
def biquad_kernel(x_in, x_out, b0, b1, b2, a1, a2, state):
    """
    state: array of shape (channels, 4) -> [x1, x2, y1, y2] per channel
    """
    frames = x_in.shape[0]
    channels = x_in.shape[1]

    for c in range(channels):
        x1 = state[c, 0]
        x2 = state[c, 1]
        y1 = state[c, 2]
        y2 = state[c, 3]

        for i in range(frames):
            x0 = x_in[i, c]
            
            # Difference equation
            y0 = b0*x0 + b1*x1 + b2*x2 - a1*y1 - a2*y2
            
            x_out[i, c] = y0

            # Shift state
            x2 = x1
            x1 = x0
            y2 = y1
            y1 = y0
        
        # Save state back
        state[c, 0] = x1
        state[c, 1] = x2
        state[c, 2] = y1
        state[c, 3] = y2

class FilterEffect(ab.Effect):
    def __init__(self, filter_type=0.0, cutoff_hz=1000.0, q=0.707):
        # filter_type: 0=LowPass, 1=HighPass, 2=BandPass
        self.filter_type = ab.SmoothParam(filter_type, 0.0, 2.0)
        self.cutoff_hz = ab.SmoothParam(cutoff_hz, 20.0, 20000.0)
        self.q = ab.SmoothParam(q, 0.1, 10.0)

        self._state = np.zeros((1, 4), dtype=np.float32)
        self._fs = 48000.0

    def set_filter_type(self, v): self.filter_type.set_target(v)
    def set_cutoff_hz(self, v): self.cutoff_hz.set_target(v)
    def set_q(self, v): self.q.set_target(v)

    def prepare(self, sample_rate: int, channels_in: int, channels_out: int, blocksize: int):
        self._fs = float(sample_rate)
        # Re-allocate state if channel count changes
        if self._state.shape[0] != channels_out:
            self._state = np.zeros((channels_out, 4), dtype=np.float32)

    def _calc_coeffs(self, f_type_val, fc, q):
        # RBJ Cookbook Biquad Formulas
        w0 = 2.0 * math.pi * fc / self._fs
        cos_w0 = math.cos(w0)
        sin_w0 = math.sin(w0)
        alpha = sin_w0 / (2.0 * q)

        b0 = b1 = b2 = a0 = a1 = a2 = 0.0
        
        # Determine integer type
        t = int(round(f_type_val))

        if t == 0: # Low Pass
            b0 =  (1 - cos_w0) / 2
            b1 =   1 - cos_w0
            b2 =  (1 - cos_w0) / 2
            a0 =   1 + alpha
            a1 =  -2 * cos_w0
            a2 =   1 - alpha
        elif t == 1: # High Pass
            b0 =  (1 + cos_w0) / 2
            b1 = -(1 + cos_w0)
            b2 =  (1 + cos_w0) / 2
            a0 =   1 + alpha
            a1 =  -2 * cos_w0
            a2 =   1 - alpha
        else: # Band Pass (constant skirt gain, peak = Q)
            # Normalize to 0dB peak gain for musical utility
            b0 =   alpha
            b1 =   0
            b2 =  -alpha
            a0 =   1 + alpha
            a1 =  -2 * cos_w0
            a2 =   1 - alpha

        # Normalize by a0
        return (b0/a0, b1/a0, b2/a0, a1/a0, a2/a0)

    def process_into(self, x_in: np.ndarray, out: np.ndarray) -> None:
        # 1. Update params
        f_type = self.filter_type.step_towards(1.0) # Changes instantly (snap to int logic)
        fc = self.cutoff_hz.step_towards(self.cutoff_hz.current * 0.1) # Log-ish feel
        q_val = self.q.step_towards(0.1)

        # 2. Calculate coefficients for this block
        b0, b1, b2, a1, a2 = self._calc_coeffs(f_type, fc, q_val)

        # 3. Ensure input matches output channels (copy mono to stereo if needed for state)
        # But standard Effect chain handles buffers. We assume out has correct shape.
        
        # 4. Run Kernel
        biquad_kernel(x_in, out, b0, b1, b2, a1, a2, self._state)
