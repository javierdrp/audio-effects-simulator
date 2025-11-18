# Start JACK in qjackctl (Driver: alsa, Interface: 1,0, 48 kHz, Frames/Period 256 to start, Periods 3).
# zita-j2a -d hw:1,0 -r 48000 -p 256 -n 3 -c 2 -j phones
import sys
from typing import Optional
import sounddevice as sd
import numpy as np
import threading
import gc

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


def pick_devices(ch_in=1, ch_out=2, in_hint=('usb','mic'), out_hint=('system',)):
    """Return (in_idx, out_idx) preferring JACK, else Pulse."""
    apis = sd.query_hostapis()
    jack_id  = next((i for i,a in enumerate(apis) if 'JACK'  in a['name']), None)
    pulse_id = next((i for i,a in enumerate(apis) if 'Pulse' in a['name']), None)

    def find_on_api(api_id, want_in, want_out, name_tokens):
        name_tokens = tuple(t.lower() for t in name_tokens)
        for i, d in enumerate(sd.query_devices()):
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
        pulse_idx = next(i for i,d in enumerate(sd.query_devices()) if d['hostapi']==pulse_id)
        return pulse_idx, pulse_idx

    # As a last resort, let PortAudio use OS defaults
    return None, None


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


def warmup_chain(chain):
    frames = chain.bs
    dummy_in  = np.zeros((frames, chain.ci), np.float32)
    dummy_out = np.zeros((frames, chain.co), np.float32)
    for _ in range(2):
        chain.process(dummy_in, dummy_out)


def main():
    gc.disable()

    chain = ab.EffectsChain(SAMPLE_RATE, CHANNELS_IN, CHANNELS_OUT, BLOCKSIZE)
    delay_fx = ab.StereoDelayEffect(max_delay_ms=MAX_DELAY_MS, mix_dry=MIX_DRY, mix_wet=MIX_WET, offset_ms=STEREO_OFFSET_MS)
    reverb_fx = ab.ReverbEffect(mix_wet=0.3, rt60_s=5, damp=0.4, pre_delay_ms=10.0)
    chain.add(delay_fx)
    chain.add(reverb_fx)
    
    warmup_chain(chain)

    threading.Thread(target=input_thread, daemon=True).start()

    status_count = 0
    max_step_ms = (1000.0 * BLOCKSIZE) / SAMPLE_RATE

    in_idx, out_idx = pick_devices(CHANNELS_IN, CHANNELS_OUT, in_hint=('usb','mic'), out_hint=('system',))
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