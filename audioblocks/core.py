from __future__ import annotations
import numpy as np
import threading


def pick_devices(ch_in=1, ch_out=2, in_hint=('usb','mic'), out_hint=('system',)):
    """Return (in_idx, out_idx) preferring JACK, else Pulse."""
    apis: list[dict[str, Any]] = sd.query_hostapis() # type: ignore
    jack_id  = next((i for i,a in enumerate(apis) if 'JACK'  in a['name']), None)
    pulse_id = next((i for i,a in enumerate(apis) if 'Pulse' in a['name']), None)
    devices: list[dict[str, Any]] = sd.query_devices() # type: ignore

    def find_on_api(api_id, want_in, want_out, name_tokens):
        name_tokens = tuple(t.lower() for t in name_tokens)
        for i, d in enumerate(devices):
            if d['hostapi'] != api_id:
                continue
            name = d['name'].lower()
            if not all(tok in name for tok in name_tokens):
                continue
            ok_in  = (not want_in)  or d['max_input_channels']  >= ch_in
            ok_out = (not want_out) or d['max_output_channels'] >= ch_out
            if ok_in and ok_out:
                return i
        return None

    # Try JACK first
    if jack_id is not None:
        in_idx  = find_on_api(jack_id,  True,  False, in_hint)   # e.g. ('usb','mic')
        out_idx = find_on_api(jack_id,  False, True,  out_hint)  # e.g. ('system',)
        if in_idx is not None and out_idx is not None:
            return in_idx, out_idx

    # Fallback: Pulse (single endpoint that you can reroute in pavucontrol)
    if pulse_id is not None:
        # often both are the same "pulse" device
        pulse_idx = next(i for i,d in enumerate(devices) if d['hostapi']==pulse_id)
        return pulse_idx, pulse_idx

    # As a last resort, let PortAudio use OS defaults
    return None, None


class SmoothParam:
    def __init__(self, value, lo=-np.inf, hi=np.inf):
        self.current = float(value)
        self.target = float(value)
        self.lo = float(lo)
        self.hi = float(hi)
        self._lock = threading.Lock()

    def set_target(self, v):
        with self._lock:
            self.target = min(max(float(v), self.lo), self.hi)

    def nudge(self, dv):
        with self._lock:
            self.target = min(max(self.target + float(dv), self.lo), self.hi)

    def step_towards(self, max_step=1.0):
        if max_step < 0:
            raise ValueError("max_step must be >= 0")
        with self._lock:
            delta = self.target - self.current
            self.current += min(max(delta, -max_step), max_step)
            return self.current


class Effect:
    """Base effect: prepare() for (re)alloc, process_into() to write output."""
    def prepare(self, sample_rate: int, channels_in: int, channels_out: int, blocksize: int):
        pass
    def process_into(self, x_in: np.ndarray, out: np.ndarray) -> None:
        raise NotImplementedError
    

class EffectsChain:
    def __init__(self, sample_rate: int, channels_in: int, channels_out: int, blocksize: int):
        self.sr = sample_rate
        self.ci = channels_in
        self.co = channels_out
        self.bs = blocksize
        self.effects: list[Effect] = []
        self._bufA = np.zeros((blocksize, channels_out), dtype=np.float32)
        self._bufB = np.zeros((blocksize, channels_out), dtype=np.float32)

    def add(self, effect: Effect):
        effect.prepare(self.sr, self.ci, self.co, self.bs)
        self.effects.append(effect)

    def _ensure_blocksize(self, frames: int):
        if frames != self.bs:
            self.bs = frames
            self._bufA = np.zeros((frames, self.co), dtype=np.float32)
            self._bufB = np.zeros((frames, self.co), dtype=np.float32)
            for e in self.effects:
                e.prepare(self.sr, self.ci, self.co, frames)

    def warmup(self):
        frames = self.bs
        dummy_in  = np.zeros((frames, self.ci), np.float32)
        dummy_out = np.zeros((frames, self.co), np.float32)
        for _ in range(2):
            self.process(dummy_in, dummy_out)

    def process(self, in_block: np.ndarray, out_block: np.ndarray):
        """
        in_block: (frames, ci) float32
        out_block: (frames, co) float32
        """
        frames = in_block.shape[0]
        self._ensure_blocksize(frames)

        # Start signal in bufA (simple mapping mono->stereo or copy)
        if self.ci == 1 and self.co == 2:
            self._bufA[:, 0:1] = in_block[:, 0:1]
            self._bufA[:, 1:2] = in_block[:, 0:1]
        else:
            ch = min(self.ci, self.co)
            self._bufA[:, :ch] = in_block[:, :ch]
            if self.co > ch:
                self._bufA[:, ch:self.co] = 0.0

        src, dst = self._bufA, self._bufB
        for eff in self.effects:
            eff.process_into(src, dst)
            src, dst = dst, src  # ping-pong

        out_block[:, :] = src  # final buffer