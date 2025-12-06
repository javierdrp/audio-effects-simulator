from __future__ import annotations
import numpy as np
import numba
import audioblocks as ab
import math

# 1. Helper for Cubic Interpolation (Hermite)
# significantly reduces "fuzz" and aliasing compared to linear
@numba.njit(cache=True, inline='always')
def cubic_interp(x, y0, y1, y2, y3):
    c0 = y1
    c1 = 0.5 * (y2 - y0)
    c2 = y0 - 2.5 * y1 + 2.0 * y2 - 0.5 * y3
    c3 = 0.5 * (y3 - y0) + 1.5 * (y1 - y2)
    return ((c3 * x + c2) * x + c1) * x + c0

@numba.njit(cache=True, fastmath=True)
def pitch_shift_kernel_cubic(buf, w, size, x_in, x_out, phasor, step):
    frames = x_in.shape[0]
    PI_2 = 2.0 * np.pi
    
    # Pre-calculate safe size mask for faster wrapping
    # (Assumes power of 2 size would be faster with bitwise & size-1, 
    # but modulo is fine here)
    
    for i in range(frames):
        # 1. Write input
        val_in = x_in[i, 0]
        buf[w] = val_in
        
        # 2. Calculate Phasors
        p1 = phasor
        p2 = phasor + 0.5
        if p2 >= 1.0: p2 -= 1.0

        # --- TAP 1 (Cubic) ---
        # Calculate precise read position
        # We add 'size' before modulo to ensure positivity
        raw_idx1 = float(w) - (p1 * float(size)) + float(size)
        idx1_floor = int(raw_idx1)
        frac1 = raw_idx1 - idx1_floor
        
        # Get 4 samples for cubic interpolation
        # Using simple modulo for safety on all taps
        i1_0 = (idx1_floor - 1) % size
        i1_1 = idx1_floor % size
        i1_2 = (idx1_floor + 1) % size
        i1_3 = (idx1_floor + 2) % size
        
        samp1 = cubic_interp(frac1, buf[i1_0], buf[i1_1], buf[i1_2], buf[i1_3])

        # --- TAP 2 (Cubic) ---
        raw_idx2 = float(w) - (p2 * float(size)) + float(size)
        idx2_floor = int(raw_idx2)
        frac2 = raw_idx2 - idx2_floor
        
        i2_0 = (idx2_floor - 1) % size
        i2_1 = idx2_floor % size
        i2_2 = (idx2_floor + 1) % size
        i2_3 = (idx2_floor + 2) % size
        
        samp2 = cubic_interp(frac2, buf[i2_0], buf[i2_1], buf[i2_2], buf[i2_3])

        # 3. Windowing (Hanning)
        # 0.5 * (1 - cos) is standard Hanning.
        gain1 = 0.5 * (1.0 - math.cos(PI_2 * p1))
        gain2 = 0.5 * (1.0 - math.cos(PI_2 * p2))

        # Sum grains (Output is 100% Wet)
        wet_sig = (samp1 * gain1 + samp2 * gain2)
        x_out[i, 0] = wet_sig

        # 4. Advance pointers
        w += 1
        if w >= size: w = 0
        
        phasor += step
        # Handle wrapping in both directions (for pitch up or down)
        if phasor >= 1.0: phasor -= 1.0
        elif phasor < 0.0: phasor += 1.0

    return w, phasor

class OctaverEffect(ab.Effect):
    def __init__(self, semitones=-12.0, mix=0.5, window_ms=40.0):
        # Parameters
        self.semitones = ab.SmoothParam(semitones, -24.0, 24.0)
        self.mix = ab.SmoothParam(mix, 0.0, 1.0)
        
        # Reduced default window to 40ms. 
        # 80ms is too long for an octaver, causing a "slurred" or "rumbly" attack.
        self.window_ms = float(window_ms)
        self._fs = 48000
        
        self.buf = np.zeros(1, dtype=np.float32)
        self.w = 0
        self.phasor = 0.0
        self.size = 1

    def set_semitones(self, v): self.semitones.set_target(v)
    def set_mix(self, v): self.mix.set_target(v)

    def prepare(self, sample_rate: int, channels_in: int, channels_out: int, blocksize: int):
        self._fs = sample_rate
        # Ensure minimum buffer size to prevent crash
        req_size = max(int(self._fs * self.window_ms / 1000.0), 16)
        
        if req_size != self.size:
            self.size = req_size
            self.buf = np.zeros(self.size, dtype=np.float32)
            # We don't reset w/phasor here to avoid clicks if parameters change live,
            # but we must ensure w is within bounds.
            self.w = 0 
            self.phasor = 0.0

    def process_into(self, x_in: np.ndarray, out: np.ndarray) -> None:
        semi = self.semitones.step_towards(0.5)
        mix_now = self.mix.step_towards(0.05)

        # Calculate step
        ratio = 2.0 ** (semi / 12.0)
        step = (1.0 - ratio) / self.size

        # Create mono input (average of channels)
        if x_in.shape[1] > 1:
            mono_in = np.mean(x_in, axis=1, keepdims=True)
        else:
            mono_in = x_in

        # Helper buffer for wet output
        mono_wet = np.zeros_like(mono_in)
        
        # Run Kernel (Outputs Pure Wet Signal)
        self.w, self.phasor = pitch_shift_kernel_cubic(
            self.buf, self.w, self.size, 
            mono_in, mono_wet, 
            self.phasor, step
        )

        # Mix Dry/Wet in the wrapper, not the kernel
        # This prevents gain staging errors.
        # Equal Power crossfade or simple linear blend:
        dry_gain = 1.0 - mix_now
        wet_gain = mix_now
        
        # If input is stereo, we apply mono wet signal to both channels
        for ch in range(out.shape[1]):
            # Use input channel for dry component to preserve stereo image of dry signal
            inp_ch = x_in[:, ch] if ch < x_in.shape[1] else x_in[:, 0]
            out[:, ch] = (inp_ch * dry_gain) + (mono_wet[:, 0] * wet_gain)
