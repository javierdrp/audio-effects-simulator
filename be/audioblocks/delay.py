from __future__ import annotations
import numpy as np
import numba

import audioblocks as ab

@numba.njit(cache=True, fastmath=True)
def delay_kernel(buf, w, size, x_block, wet_out, dS, feedback):
    """
    buf: (size,) float32 ring buffer
    x_block, wet_out: (N,1) float32
    """
    N = x_block.shape[0]
    for n in range(N):
        r = (w - dS) % size
        delayed = buf[r]
        wet_out[n, 0] = delayed
        buf[w] = x_block[n, 0] + delayed * feedback
        w += 1
        if w == size:
            w = 0
    return w

class DelayLine:
    def __init__(self):
        self.fs = 48000
        self.size = 1
        self.buf = np.zeros(1, dtype=np.float32)
        self.w = 0

    def configure(self, fs: int, max_delay_ms: float):
        self.fs = fs
        self.size = int(fs * max_delay_ms / 1000.0) + 1
        self.buf  = np.zeros(self.size, dtype=np.float32)
        self.w = 0

    def process_into(self, x_block: np.ndarray, wet_out: np.ndarray, delay_ms: float, feedback: float):
        dS = int(self.fs * delay_ms / 1000.0)
        if dS >= self.size:
            dS = self.size - 1
        self.w = delay_kernel(self.buf, self.w, self.size, x_block, wet_out, dS, feedback)

class StereoDelayEffect(ab.Effect):
    """
    Mono-in/stereo-out delay (or stereo-through), independent L/R delay lines.
    Uses a small offset on R for width. Mix = dry + wet inside the effect.
    """
    def __init__(self, max_delay_ms=1500.0, mix_dry=0.8, mix_wet=0.8, offset_ms=30.0, delay_ms=375.0, feedback=0.2, fb_step=0.02, step_samples=2.0):
        self.max_delay_ms = max_delay_ms
        self.mix_dry = mix_dry
        self.mix_wet = mix_wet
        self.offset_ms = offset_ms

        self.delay_ms = ab.SmoothParam(delay_ms, 1.0, max_delay_ms - 1.0)
        self.feedback = ab.SmoothParam(feedback, 0.0, 0.95)
        # smoothing config
        self._fb_step = fb_step            # feedback step per block (unitless)
        self._step_samples = step_samples  # convert to ms in prepare()

        self._dlL = DelayLine()
        self._dlR = DelayLine()
        self._wetL = np.empty((1, 1), dtype=np.float32)
        self._wetR = np.empty((1, 1), dtype=np.float32)
        self._delay_step_ms = 0.1

    def set_delay_ms(self, v: float): self.delay_ms.set_target(v)
    def nudge_delay_ms(self, dv: float): self.delay_ms.nudge(dv)
    def set_feedback(self, v: float): self.feedback.set_target(v)

    def prepare(self, sample_rate: int, channels_in: int, channels_out: int, blocksize: int):
        self._dlL.configure(sample_rate, self.max_delay_ms)
        self._dlR.configure(sample_rate, self.max_delay_ms)
        self._wetL = np.empty((blocksize, 1), dtype=np.float32)
        self._wetR = np.empty((blocksize, 1), dtype=np.float32)
        self._delay_step_ms = 1000.0 * (self._step_samples / sample_rate)

    def process_into(self, x_in: np.ndarray, out: np.ndarray):
        # smooth parameters
        dL_now = self.delay_ms.step_towards(self._delay_step_ms)
        fb_now = self.feedback.step_towards(self._fb_step)
        dR_now = min(dL_now + self.offset_ms, self.max_delay_ms - 1.0)

        # Expect x_in to be stereo in the chain; if mono duplicated, both columns are the same
        xL = x_in[:, 0:1]
        xR = x_in[:, 1:2]

        self._dlL.process_into(xL, self._wetL, dL_now, fb_now)
        self._dlR.process_into(xR, self._wetR, dR_now, fb_now)

        # Mix and clip
        out[:, 0:1] = self.mix_dry * xL + self.mix_wet * self._wetL
        out[:, 1:2] = self.mix_dry * xR + self.mix_wet * self._wetR
        np.clip(out, -1.0, 1.0, out=out)