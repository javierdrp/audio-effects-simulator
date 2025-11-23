# Start JACK in qjackctl (Driver: alsa, Interface: 1,0, 48 kHz, Frames/Period 256 to start, Periods 3).
# zita-j2a -d hw:1,0 -r 48000 -p 256 -n 3 -c 2 -j phones

import sys
import sounddevice as sd
import numpy as np
import threading
import gc
import argparse
import soundfile as sf
import queue

import audioblocks_bk as ab


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

delay_fx = ab.StereoDelayEffect()


def plot_consumer_thread(data_queues: dict[str, queue.Queue]):
    while True:
        try:
            in_data = data_queues["input"].get(timeout=0.1)
            print(f"Received input data block of shape: {in_data.shape}")
        except queue.Empty:
            pass

        try:
            out_data = data_queues["output"].get(timeout=0.1)
            print(f"Received output data block of shape: {out_data.shape}")
        except queue.Empty:
            pass


def build_effects_chain(sample_rate: int, channels_in: int, channels_out: int, blocksize: int, effects: list[ab.Effect]):
    global delay_fx

    chain = ab.EffectsChain(sample_rate, channels_in, channels_out, blocksize)
    for fx_block in effects:
        chain.add(fx_block)
    chain.warmup()

    return chain


def play_wav_through_chain(path: str, effects: list[ab.Effect], data_queues: dict[str, queue.Queue]):
    # Probe file
    with sf.SoundFile(path, mode="r") as f:
        file_sr = f.samplerate
        file_ch = f.channels

    # Build a chain that matches the file's input channel count (1 or 2)
    ci = 1 if file_ch == 1 else 2
    
    chain = build_effects_chain(file_sr, ci, CHANNELS_OUT, BLOCKSIZE, effects)

    # Start the consumer and input threads
    threading.Thread(target=plot_consumer_thread, args=(data_queues,), daemon=True).start()
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


def play_live_through_chain(effects: list[ab.Effect], data_queues: dict[str, queue.Queue]):
    chain = build_effects_chain(SAMPLE_RATE, CHANNELS_IN, CHANNELS_OUT, BLOCKSIZE, effects)

    # Start the consumer and input threads
    threading.Thread(target=plot_consumer_thread, args=(data_queues,), daemon=True).start()
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



def main():
    gc.disable()
    
    parser = argparse.ArgumentParser()
    parser.add_argument("-f", "--file", help="Process and play this WAV/AIFF file instead of mic")
    args = parser.parse_args()

    data_queues = {
        "input": queue.Queue(maxsize=10),
        "output": queue.Queue(maxsize=10)
    }

    input_tap = ab.PlotDataTap(data_queues['input'])
    output_tap = ab.PlotDataTap(data_queues['output'])

    global delay_X
    delay_fx = ab.StereoDelayEffect(max_delay_ms=MAX_DELAY_MS, mix_dry=MIX_DRY, mix_wet=MIX_WET, offset_ms=STEREO_OFFSET_MS)
    reverb_fx = ab.ReverbEffect(mix_wet=0.3, rt60_s=1, damp=0.3, pre_delay_ms=10.0)
    effects = [input_tap, delay_fx, reverb_fx, output_tap]
    
    if args.file:
        play_wav_through_chain(args.file, effects, data_queues)
        gc.enable()
    else:
        play_live_through_chain(effects, data_queues)
        

if __name__ == "__main__":
    main()