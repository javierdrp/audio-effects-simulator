# audioblocks/reverb.py (Corrected and stable version)

from __future__ import annotations
import numpy as np
import numba

import audioblocks as ab

# -------------------- Kernels --------------------

@numba.njit(cache=True, fastmath=True)
def pure_delay_kernel(buf, w, size, x_block, y_out, dS):
    N = x_block.shape[0]
    if dS == 0:
        for n in range(N):
            x = x_block[n, 0]
            y_out[n, 0] = x      # no delay
            buf[w] = x
            w += 1
            if w == size:
                w = 0
        return w

    for n in range(N):
        r = (w - dS) % size
        y_out[n, 0] = buf[r]
        buf[w] = x_block[n, 0]
        w += 1
        if w == size:
            w = 0
    return w

@numba.njit(cache=True, fastmath=True)
def comb_damped_kernel(buf, w, size, x_block, y_out, dS, g, h, lp_prev):
    N = x_block.shape[0]
    for n in range(N):
        r = (w - dS) % size
        y = buf[r]
        damped = (1.0 - h) * y + h * lp_prev
        lp_prev = damped
        y_out[n, 0] = y
        buf[w] = x_block[n, 0] + g * damped
        w += 1
        if w == size:
            w = 0
    return w, lp_prev

@numba.njit(cache=True, fastmath=True)
def allpass_kernel(buf, w, size, x_block, y_out, dS, a):
    """
    Stable Gardner/Moorer-style allpass diffuser.
    'a' is the feedback gain, typically ~0.5-0.7.
    """
    N = x_block.shape[0]
    for n in range(N):
        r = (w - dS) % size
        delayed = buf[r]
        x = x_block[n, 0]

        y = delayed - a * x
        y_out[n, 0] = y
        buf[w] = x + a * y

        w += 1
        if w == size:
            w = 0
    return w


# -------------------- Effect --------------------

class ReverbEffect(ab.Effect):
    # ... (__init__ is unchanged) ...
    def __init__(
        self,
        *,
        # topology
        comb_times_ms = (29.7, 37.1, 41.1, 43.7),
        allpass_times_ms = (5.0, 1.7),
        allpass_gain = 0.6,
        jitter_ms = 0.3,            # decorrelate L/R by +-jitter
        # limits / buffers
        max_delay_ms = 200.0,       # per-line max for combs/allpasses
        max_pre_delay_ms = 100.0,   # pre-delay cap
        # mixing
        mix_dry = 0.7,
        mix_wet = 0.5,
        # live params (targets; smoothed internally)
        rt60_s = 1.5,               # room decay time (-60 dB)
        damp = 0.3,                 # HF damping 0..1
        pre_delay_ms = 0.0,
        # smoothing config
        step_samples = 2.0,         # convert to ms based on fs during prepare()
        rt60_step = 0.05,           # per-block step
        damp_step = 0.02            # per-block step
    ):
        # topology / constants
        self._comb_ms_base = tuple(float(x) for x in comb_times_ms)
        self._ap_ms_base   = tuple(float(x) for x in allpass_times_ms)
        self._ap_gain      = float(allpass_gain)
        self._jitter_ms    = float(jitter_ms)

        # limits
        self._max_delay_ms    = float(max_delay_ms)
        self._max_pre_ms      = float(max_pre_delay_ms)

        # mix
        self.mix_dry = float(mix_dry)
        self.mix_wet = float(mix_wet)

        # smoothed live params
        self.rt60     = ab.SmoothParam(rt60_s, 0.1, 10.0)
        self.damp     = ab.SmoothParam(damp,   0.0, 0.99)
        self.pre_delay= ab.SmoothParam(pre_delay_ms, 0.0, self._max_pre_ms)

        # smoothing setup
        self._step_samples = float(step_samples)
        self._rt60_step  = float(rt60_step)
        self._damp_step  = float(damp_step)
        self._delay_step_ms = 0.1  # filled in prepare()

        # sample rate for g-from-rt60 calc
        self._fs = 48000

        # per-side networks: lists of dicts (buffers + states)
        self._comb_L = []
        self._ap_L   = []
        self._comb_R = []
        self._ap_R   = []

        # pre-delay per side
        self._pre_buf_L = np.zeros(1, np.float32)
        self._pre_w_L   = 0
        self._pre_buf_R = np.zeros(1, np.float32)
        self._pre_w_R   = 0

        # scratch
        self._tmp1 = np.empty((1,1), np.float32)
        self._tmp2 = np.empty((1,1), np.float32)
        self._sumL = np.empty((1,1), np.float32)
        self._sumR = np.empty((1,1), np.float32)
        self._preL = np.empty((1,1), np.float32)
        self._preR = np.empty((1,1), np.float32)


    # setters
    def set_rt60(self, seconds: float):     self.rt60.set_target(seconds)
    def set_damp(self, value: float):       self.damp.set_target(value)
    def set_pre_delay(self, ms: float):     self.pre_delay.set_target(ms)
    def set_mix(self, dry: float | None = None, wet: float | None = None):
        if dry is not None: self.mix_dry = float(dry)
        if wet is not None: self.mix_wet = float(wet)
    def set_mix_wet(self, wet: float): self.mix_wet = wet

    # -------------------- lifecycle --------------------

    def _mk_side(self, sample_rate: int, jitter: float):
        comb = []
        for base_ms in self._comb_ms_base:
            ms = min(base_ms + jitter, self._max_delay_ms - 1.0)
            Lsamp = int(sample_rate * ms / 1000.0)
            Lsamp = max(1, Lsamp)
            buf = np.zeros(Lsamp + 1, np.float32)
            comb.append({'buf': buf, 'w': 0, 'L': Lsamp, 'lp': 0.0})

        ap = []
        for base_ms in self._ap_ms_base:
            ms = min(base_ms + jitter*0.2, self._max_delay_ms - 1.0)
            Lsamp = int(sample_rate * ms / 1000.0)
            Lsamp = max(1, Lsamp)
            buf = np.zeros(Lsamp + 1, np.float32)
            # --- START: Removed the unnecessary 'prev' state ---
            ap.append({'buf': buf, 'w': 0, 'L': Lsamp})
            # --- END: Removed 'prev' state ---

        return comb, ap

    # ... (prepare is unchanged, as the scratch buffers are still needed) ...
    def prepare(self, sample_rate: int, channels_in: int, channels_out: int, blocksize: int):
        # store fs and smoothing conversion
        self._fs = int(sample_rate)
        self._delay_step_ms = 1000.0 * (self._step_samples / float(self._fs))

        # networks per side (slight jitter to decorrelate)
        self._comb_L, self._ap_L = self._mk_side(self._fs, +self._jitter_ms)
        self._comb_R, self._ap_R = self._mk_side(self._fs, -self._jitter_ms)

        # pre-delay buffers (per side)
        pre_size = int(self._fs * self._max_pre_ms / 1000.0) + 1
        pre_size = max(1, pre_size)
        self._pre_buf_L = np.zeros(pre_size, np.float32); self._pre_w_L = 0
        self._pre_buf_R = np.zeros(pre_size, np.float32); self._pre_w_R = 0

        # scratch
        self._tmp1 = np.empty((blocksize, 1), np.float32)
        self._tmp2 = np.empty((blocksize, 1), np.float32)
        self._sumL = np.empty((blocksize, 1), np.float32)
        self._sumR = np.empty((blocksize, 1), np.float32)
        self._preL = np.empty((blocksize, 1), np.float32)
        self._preR = np.empty((blocksize, 1), np.float32)

    # -------------------- processing --------------------

    def _g_from_rt60(self, L_samples: int, fs: int, rt60_s: float) -> float:
        return 10.0 ** (-3.0 * (float(L_samples) / float(fs)) / max(1e-3, rt60_s))

    def process_into(self, x_in: np.ndarray, out: np.ndarray):
        N = x_in.shape[0]
        if self._sumL.shape[0] != N:
            # (This block for resizing scratch buffers is fine)
            self._tmp1 = np.empty((N,1), np.float32)
            self._tmp2 = np.empty((N,1), np.float32)
            self._sumL = np.empty((N,1), np.float32)
            self._sumR = np.empty((N,1), np.float32)
            self._preL = np.empty((N,1), np.float32)
            self._preR = np.empty((N,1), np.float32)

        # smooth params
        rt60_now   = self.rt60.step_towards(self._rt60_step)
        damp_now   = self.damp.step_towards(self._damp_step)
        pre_ms_now = self.pre_delay.step_towards(self._delay_step_ms)
        pre_dS     = int(self._fs * pre_ms_now / 1000.0)
        if pre_dS >= self._pre_buf_L.shape[0]:
            pre_dS = self._pre_buf_L.shape[0] - 1

        xL = x_in[:, 0:1].copy()
        xR = x_in[:, 1:2].copy()

        # pre-delay
        self._pre_w_L = pure_delay_kernel(self._pre_buf_L, self._pre_w_L, self._pre_buf_L.shape[0], xL, self._preL, pre_dS)
        self._pre_w_R = pure_delay_kernel(self._pre_buf_R, self._pre_w_R, self._pre_buf_R.shape[0], xR, self._preR, pre_dS)

        # Left comb sum
        self._sumL.fill(0.0)
        for c in self._comb_L:
            g = self._g_from_rt60(c['L'], self._fs, rt60_now)
            new_w, new_lp = comb_damped_kernel(c['buf'], c['w'], c['buf'].shape[0],
                                            self._preL, self._tmp1, c['L'], g, damp_now, c['lp'])
            c['w'], c['lp'] = new_w, new_lp
            self._sumL += self._tmp1

        # Left All-pass chain (using ping-pong buffering from previous fix)
        src, dst = self._sumL, self._tmp1
        for a in self._ap_L:
            # --- START: Call the corrected kernel ---
            new_w = allpass_kernel(a['buf'], a['w'], a['buf'].shape[0],
                                   src, dst, a['L'], self._ap_gain)
            a['w'] = new_w
            # --- END: Call the corrected kernel ---
            src, dst = dst, src
        yL = src

        # Right comb sum
        self._sumR.fill(0.0)
        for c in self._comb_R:
            g = self._g_from_rt60(c['L'], self._fs, rt60_now)
            new_w, new_lp = comb_damped_kernel(c['buf'], c['w'], c['buf'].shape[0],
                                            self._preR, self._tmp1, c['L'], g, damp_now, c['lp'])
            c['w'], c['lp'] = new_w, new_lp
            self._sumR += self._tmp1

        # Right All-pass chain
        src, dst = self._sumR, self._tmp1
        for a in self._ap_R:
            # --- START: Call the corrected kernel ---
            new_w = allpass_kernel(a['buf'], a['w'], a['buf'].shape[0],
                                   src, dst, a['L'], self._ap_gain)
            a['w'] = new_w
            # --- END: Call the corrected kernel ---
            src, dst = dst, src
        yR = src

        # Mix and clip
        out[:, 0:1] = self.mix_dry * xL + self.mix_wet * yL
        out[:, 1:2] = self.mix_dry * xR + self.mix_wet * yR
        np.clip(out, -1.0, 1.0, out=out)