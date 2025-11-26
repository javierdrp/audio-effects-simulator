from __future__ import annotations
import numpy as np
import numba
import audioblocks as ab

@numba.njit(cache=True, fastmath=True)
def pitch_shift_kernel(buf, w, size, x_in, x_out, phasor, step, mix_wet):
    """
    buf: Circular buffer
    w: Write pointer (int)
    phasor: float (0.0 to 1.0), position of the read window
    step: float, how much to increment phasor per sample
    """
    frames = x_in.shape[0]
    
    # Pre-calculate half-size for the second tap offset
    half_size = 0.5

    for i in range(frames):
        # 1. Write input to circular buffer
        val_in = x_in[i, 0] # assume mono processing, applied to stereo later
        buf[w] = val_in
        
        # 2. Calculate Read Pointers
        # We need two taps, 180 degrees out of phase (0.0 and 0.5)
        # The 'phasor' represents the relative distance from the write head (0 to size)
        
        # Tap 1
        p1 = phasor
        # Tap 2 (offset by half the window)
        p2 = phasor + 0.5
        if p2 >= 1.0: p2 -= 1.0

        # Convert 0..1 to buffer indices (delay behind write head)
        # If phasor is 0, delay is 0. If phasor is 1, delay is 'size'.
        idx1 = (w - int(p1 * size)) % size
        idx2 = (w - int(p2 * size)) % size

        samp1 = buf[idx1]
        samp2 = buf[idx2]

        # 3. Windowing (Crossfade)
        # We use a triangle window. 
        # Gain is 1.0 when phasor is 0.5, and 0.0 when phasor is 0.0 or 1.0
        # This hides the "click" when the phasor wraps around.
        gain1 = 1.0 - 2.0 * abs(p1 - 0.5)
        gain2 = 1.0 - 2.0 * abs(p2 - 0.5)

        # Sum the two grains
        wet_sig = (samp1 * gain1 + samp2 * gain2)

        # 4. Output Mixing
        # (Simple equal power mix or linear mix)
        x_out[i, 0] = (1.0 - mix_wet) * val_in + mix_wet * wet_sig

        # 5. Advance pointers
        w += 1
        if w == size: w = 0
        
        phasor += step
        if phasor >= 1.0: phasor -= 1.0
        elif phasor < 0.0: phasor += 1.0

    return w, phasor


class OctaverEffect(ab.Effect):
    def __init__(self, semitones=-12.0, mix=0.5, window_ms=60.0):
        # Parameters
        self.semitones = ab.SmoothParam(semitones, -24.0, 24.0)
        self.mix = ab.SmoothParam(mix, 0.0, 1.0)
        
        # Internal configuration
        self.window_ms = float(window_ms)
        self._fs = 48000
        
        # Buffer
        self.buf = np.zeros(1, dtype=np.float32)
        self.w = 0
        self.phasor = 0.0
        self.size = 1

    def set_semitones(self, v): self.semitones.set_target(v)
    def set_mix(self, v): self.mix.set_target(v)

    def prepare(self, sample_rate: int, channels_in: int, channels_out: int, blocksize: int):
        self._fs = sample_rate
        # Calculate buffer size based on window_ms
        # A larger window sounds smoother but "slushier". 
        # A shorter window sounds tighter but more "robotic/metallic".
        req_size = int(self._fs * self.window_ms / 1000.0)
        if req_size != self.size:
            self.size = req_size
            self.buf = np.zeros(self.size, dtype=np.float32)
            self.w = 0
            self.phasor = 0.0

    def process_into(self, x_in: np.ndarray, out: np.ndarray) -> None:
        # 1. Update params
        semi = self.semitones.step_towards(0.5) # smooth pitch change
        mix_now = self.mix.step_towards(0.05)

        # 2. Calculate Pitch Ratio and Phasor Step
        # Ratio: 0.5 = octave down, 2.0 = octave up, 1.0 = unison
        ratio = 2.0 ** (semi / 12.0)
        
        # The phasor step determines how fast the read head moves relative to write.
        # step = -(ratio - 1) / size
        # If ratio is 1.0, step is 0 (read head stays at fixed distance).
        # If ratio is 0.5 (slower), step is positive (read head gets dragged along).
        step = (1.0 - ratio) / self.size

        # 3. Process (Mono logic applied to stereo for efficiency)
        # We process the first channel and copy to both for the wet signal
        # effectively making the octaver mono-summed (common for bass effects),
        # but we preserve the dry stereo image in the kernel if we passed both,
        # but here we simplify to mono-wet.
        
        # Mix down to mono for the effect input
        mono_in = np.mean(x_in, axis=1, keepdims=True)
        mono_out = np.zeros_like(mono_in)
        
        self.w, self.phasor = pitch_shift_kernel(
            self.buf, self.w, self.size, 
            mono_in, mono_out, 
            self.phasor, step, 1.0 # process wet only inside kernel
        )

        # 4. Mix Dry/Wet into Output
        # The kernel calculated pure wet for mono_out.
        # We manually mix here to preserve stereo dry.
        
        # Left
        out[:, 0] = (1.0 - mix_now) * x_in[:, 0] + mix_now * mono_out[:, 0]
        # Right
        if out.shape[1] > 1:
            out[:, 1] = (1.0 - mix_now) * x_in[:, 1] + mix_now * mono_out[:, 0]
