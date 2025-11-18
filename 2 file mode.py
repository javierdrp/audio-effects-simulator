# Start JACK in qjackctl (Driver: alsa, Interface: 1,0, 48 kHz, Frames/Period 256 to start, Periods 3).
# zita-j2a -d hw:1,0 -r 48000 -p 256 -n 3 -c 2 -j phones
import sys
from typing import Optional, Any
import sounddevice as sd
import numpy as np
import threading
import gc
import argparse
import soundfile as sf

import audioblocks as ab


SAMPLE_RATE  = 48000
BLOCKSIZE    = 256
CHANNELS_IN  = 1
CHANNELS_OUT  = 2

# delay params
MAX_DELAY_MS = 1500
DELAY_MS     = 375
FEEDBACK     = 0.5
MIX_DRY      = 0.8
MIX_WET      = 0.8
STEREO_OFFSET_MS = 30


def print_help():
    print("\nControls:")
    print("  d +N    -> increases delay N ms (e.g. 'd +50')")
    print("  d -N    -> reduces delay N ms (e.g. 'd -20')")
    print("  d N     -> sets delay at N ms (e.g. 'd 350')")
    print("  f X     -> sets feedback at X (0..0.95, e.g. 'f 0.45')")
    print("  h       -> help")
    print("  Ctrl+C  -> quit\n")


def input_thread():
    print_help()
    for line in sys.stdin:
        s = line.strip().lower()
        if not s:
            continue
        try:
            if s == 'h':
                print_help()
            elif s.startswith('d '):
                arg = s[2:].strip()
                if arg.startswith(('+', '-')):
                    delay_fx.nudge_delay_ms(float(arg))
                else:
                    delay_fx.set_delay_ms(float(arg))
                print(f"delay target -> {delay_fx.delay_ms.target:.1f} ms")
            elif s.startswith('f '):
                x = float(s[2:].strip())
                delay_fx.set_feedback(x)
                print(f"feedback -> {delay_fx.feedback.target:.2f}")
        except Exception as e:
            print("Invalid command:", e)


def play_wav_through_chain(path: str):
    # Probe file
    with sf.SoundFile(path, mode="r") as f:
        file_sr = f.samplerate
        file_ch = f.channels

    # Build a chain that matches the file's input channel count (1 or 2)
    ci = 1 if file_ch == 1 else 2

    # Reuse the same style of effects; update the global delay_fx so the CLI controls it
    global delay_fx
    delay_fx = ab.StereoDelayEffect(max_delay_ms=MAX_DELAY_MS, mix_dry=MIX_DRY,
                                    mix_wet=MIX_WET, offset_ms=STEREO_OFFSET_MS)
    reverb_fx = ab.ReverbEffect(mix_wet=0.3, rt60_s=1, damp=0.3, pre_delay_ms=10.0)

    chain = ab.EffectsChain(file_sr, ci, CHANNELS_OUT, BLOCKSIZE)
    # chain.add(delay_fx); 
    chain.add(reverb_fx)
    chain.warmup()

    # Keep the same controls while the file plays
    threading.Thread(target=input_thread, daemon=True).start()

    # Pick output device (or None = system default)
    _, out_idx = ab.pick_devices(ci, CHANNELS_OUT, in_hint=(), out_hint=('system',))
    device_pair = (None, out_idx) if out_idx is not None else None

    # Output stream at the file's samplerate
    with sd.OutputStream(device=device_pair,
                         samplerate=file_sr,
                         blocksize=BLOCKSIZE,
                         dtype='float32',
                         channels=CHANNELS_OUT,
                         latency=(0.03, 0.03),
                         prime_output_buffers_using_stream_callback=True) as outstream:

        # Stream the file in blocks
        for block in sf.blocks(path, blocksize=BLOCKSIZE, dtype='float32', always_2d=True):
            # Shape to chain input (ci)
            if ci == 1:
                x = block[:, :1] if block.shape[1] == 1 else block.mean(axis=1, keepdims=True)
            else:
                x = block[:, :2] if block.shape[1] >= 2 else np.repeat(block, 2, axis=1)

            out = np.empty((x.shape[0], CHANNELS_OUT), dtype=np.float32)
            chain.process(x, out)
            outstream.write(out)

        # Flush a short tail so the reverb decays (about 1.5 s)
        tail_frames = int(3.0 * file_sr)
        zeros = np.zeros((BLOCKSIZE, ci), dtype=np.float32)
        while tail_frames > 0:
            n = min(BLOCKSIZE, tail_frames)
            xz = zeros[:n]
            out = np.empty((n, CHANNELS_OUT), dtype=np.float32)
            chain.process(xz, out)
            outstream.write(out)
            tail_frames -= n



delay_fx = ab.StereoDelayEffect()


def render_reverb_ir(seconds=3.0, sr=48000, ci=2, co=2, path="reverb_ir.wav"):
    import soundfile as sf
    chain = ab.EffectsChain(sr, ci, co, BLOCKSIZE)

    # Reverb only, 100% wet so it can’t be mistaken for dry
    rev = ab.ReverbEffect(
        mix_dry=0.0, mix_wet=1.0,
        rt60_s=1.2, damp=0.2, pre_delay_ms=0.0,
        # make early energy obvious (shorter combs help audibility)
        comb_times_ms=(10.0, 12.0, 15.0, 18.0),
        allpass_times_ms=(4.0, 2.0)
    )
    chain.add(rev)
    chain.warmup()

    total = int(seconds * sr)
    frames_left = total
    out_blocks = []
    first = True
    while frames_left > 0:
        n = min(BLOCKSIZE, frames_left)
        x = np.zeros((n, ci), np.float32)
        if first:
            x[0, 0] = 1.0  # left impulse
            first = False
        y = np.empty((n, co), np.float32)
        chain.process(x, y)
        out_blocks.append(y.copy())
        frames_left -= n

    ycat = np.vstack(out_blocks)
    peak = float(np.max(np.abs(ycat)))
    print(f"[IR] wrote {path}, peak={peak:.6f}")
    sf.write(path, ycat, sr)


def main():
    global delay_fx
    gc.disable()

    parser = argparse.ArgumentParser()
    parser.add_argument("--ir", action="store_true", help="Render reverb impulse response to reverb_ir.wav")
    parser.add_argument("-f", "--file", help="Process and play this WAV/AIFF file instead of mic")
    args = parser.parse_args()

    if args.ir:
        render_reverb_ir()
        return
    if args.file:
        play_wav_through_chain(args.file)
        gc.enable()
        return

    chain = ab.EffectsChain(SAMPLE_RATE, CHANNELS_IN, CHANNELS_OUT, BLOCKSIZE)
    delay_fx = ab.StereoDelayEffect(max_delay_ms=MAX_DELAY_MS, mix_dry=MIX_DRY, mix_wet=MIX_WET, offset_ms=STEREO_OFFSET_MS)
    reverb_fx = ab.ReverbEffect(mix_wet=0.3, rt60_s=1, damp=0.3, pre_delay_ms=10.0)
    chain.add(delay_fx)
    chain.add(reverb_fx)
    chain.warmup()

    threading.Thread(target=input_thread, daemon=True).start()

    status_count = 0

    in_idx, out_idx = ab.pick_devices(CHANNELS_IN, CHANNELS_OUT, in_hint=('usb','mic'), out_hint=('system',))
    print("Using devices:", in_idx, out_idx)

    device_pair = (in_idx, out_idx) if (in_idx is not None and out_idx is not None) else None
    
    def callback(indata, outdata, frames, time, status):
        nonlocal status_count
        if status:
            status_count += 1
        chain.process(indata, outdata)

    try:
        with sd.Stream(device=device_pair, samplerate=SAMPLE_RATE, blocksize=BLOCKSIZE, latency=(0.03, 0.03), dtype='float32', channels=(CHANNELS_IN, CHANNELS_OUT), callback=callback, prime_output_buffers_using_stream_callback=True):
            sd.sleep(10**9)   # run indefinitely
    except KeyboardInterrupt:
        gc.enable()
        print("\nClosing...")
        print("Audio status events:", status_count)
    except Exception as e:
        print("Audio error:", e)
        

if __name__ == "__main__":
    main()