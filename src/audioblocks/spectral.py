from __future__ import annotations
import numpy as np
import audioblocks as ab

class SpectralFilter(ab.Effect):
    def __init__(self, threshold_db=-40.0, reduction=0.5, smoothing=0.8):
        # Params
        self.threshold_db = ab.SmoothParam(threshold_db, -80.0, 0.0)
        self.reduction = ab.SmoothParam(reduction, 0.0, 1.0) # 0.0 = silence noise, 1.0 = hear noise
        
        # FFT Config (Overlap-Add method)
        self.blocksize = 256
        self.n_fft = 512  # 2x blocksize for 50% overlap
        self.hop = 256
        
        # Hanning window for smooth overlaps
        self.window = np.hanning(self.n_fft).astype(np.float32)
        
        # Buffers
        self.in_buffer = np.zeros(self.n_fft, dtype=np.float32)
        self.out_accum = np.zeros(self.n_fft, dtype=np.float32)
        
        # State for temporal smoothing (prevents "watery" artifacts)
        self.mask_smooth = np.ones(self.n_fft // 2 + 1, dtype=np.float32)
        self.alpha_param = smoothing # simple float, not automated for now

    def set_threshold_db(self, v): self.threshold_db.set_target(v)
    def set_reduction(self, v): self.reduction.set_target(v)

    def prepare(self, sample_rate: int, channels_in: int, channels_out: int, blocksize: int):
        # We assume blocksize matches our hop size (256) for simplicity in this demo.
        # If the engine changes blocksize dynamically, this simple implementation might drift,
        # but for fixed 256/48k it is stable.
        if blocksize != self.hop:
            # Re-init if blocksize changes
            self.blocksize = blocksize
            self.hop = blocksize
            self.n_fft = blocksize * 2
            self.window = np.hanning(self.n_fft).astype(np.float32)
            self.in_buffer = np.zeros(self.n_fft, dtype=np.float32)
            self.out_accum = np.zeros(self.n_fft, dtype=np.float32)
            self.mask_smooth = np.ones(self.n_fft // 2 + 1, dtype=np.float32)

    def process_into(self, x_in: np.ndarray, out: np.ndarray) -> None:
        # 1. Update params
        th_db = self.threshold_db.step_towards(1.0)
        red_amount = self.reduction.step_towards(0.05)
        
        threshold_linear = 10.0 ** (th_db / 20.0)

        # 2. Input Processing (Mono mix for analysis, but we apply to stereo)
        # Shift input buffer and append new block
        self.in_buffer[:-self.hop] = self.in_buffer[self.hop:]
        # Mix to mono for detection to save CPU
        mono_in = np.mean(x_in, axis=1)
        self.in_buffer[-self.hop:] = mono_in * 1.0 # Simple copy

        # 3. FFT
        # Apply window to current analysis frame
        fft_in = np.fft.rfft(self.in_buffer * self.window)
        
        # 4. Spectral Gating Logic
        magnitude = np.abs(fft_in)
        phase = np.angle(fft_in)

        # Determine mask: 1.0 if loud, 'red_amount' if quiet
        # "Quiet" is defined per-frequency-bin compared to threshold
        current_mask = np.where(magnitude > threshold_linear, 1.0, red_amount)
        
        # Smooth mask over time to reduce artifacts (Temporal Smoothing)
        self.mask_smooth = (self.alpha_param * self.mask_smooth) + ((1.0 - self.alpha_param) * current_mask)
        
        # Apply mask
        processed_fft = magnitude * self.mask_smooth * np.exp(1j * phase)
        
        # 5. IFFT (Inverse FFT)
        processed_time = np.fft.irfft(processed_fft)
        
        # 6. Overlap-Add to Output
        # We simply add to the accumulator. 
        # (Technically we should apply a synthesis window here too for perfect reconstruction, 
        # but for noise reduction, single window + overlap is usually acceptable)
        self.out_accum += processed_time
        
        # 7. Write to output
        # Take the first 'hop' samples as valid output
        valid_out = self.out_accum[:self.hop]
        
        # Expand back to stereo (or whatever output count is)
        # Since we detected on Mono, we apply the same cleaning to both channels
        # (This assumes the noise is similar in both channels)
        if out.shape[1] == 2:
            out[:, 0] = valid_out
            out[:, 1] = valid_out
        else:
            out[:, 0] = valid_out

        # 8. Shift Output Accumulator
        self.out_accum[:-self.hop] = self.out_accum[self.hop:]
        self.out_accum[-self.hop:] = 0.0
