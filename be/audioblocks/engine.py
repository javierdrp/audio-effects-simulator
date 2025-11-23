from __future__ import annotations
import queue
import sounddevice as sd

from .core import EffectsChain, PlotDataTap, SmoothParam
from .delay import StereoDelayEffect
from .reverb import ReverbEffect


SAMPLE_RATE  = 48000
BLOCKSIZE    = 256
CHANNELS_IN  = 1
CHANNELS_OUT  = 2


class AudioEngine:
    def __init__(self, data_queues: dict[str, queue.Queue]):
        self.stream = None
        self.effects_chain = None
        self.data_queues = data_queues
        self.is_running = False
        self.effects_map = {}
        self.status_count = 0

    def build_chain(self, effects_config: list[dict]):
        chain = EffectsChain(SAMPLE_RATE, CHANNELS_IN, CHANNELS_OUT, BLOCKSIZE)
        self.effects_map.clear()

        chain.add(PlotDataTap(self.data_queues['input']))

        for config in effects_config:
            effect_id = config.get('id')
            effect_type = config.get('type')
            params = config.get('params', {})

            if effect_type == 'delay':
                fx = StereoDelayEffect(**params)
            elif effect_type == 'reverb':
                fx = ReverbEffect(**params)
            #  add other effects here
            else:
                print(f"Warning: unknown effect type '{effect_type}'")
                continue

            chain.add(fx)
            if effect_id:
                self.effects_map[effect_id] = fx

        chain.add(PlotDataTap(self.data_queues['output']))

        chain.warmup()
        self.effects_chain = chain

    def update_param(self, effect_id: str, param_name: str, value: float):
        if effect_id not in self.effects_map:
            print(f"Error: effect ID '{effect_id}' not found")
            return
        
        effect = self.effects_map[effect_id]

        # update using setter or SmoothParam
        setter_func = f"set_{param_name}"
        if hasattr(effect, setter_func):
            getattr(effect, setter_func)(value)
        elif hasattr(effect, param_name) and isinstance((att := getattr(effect, param_name)), SmoothParam):
            att.set_target(value)
        else:
            print(f"Warning: parameter '{param_name}' in effect '{effect_id}' could not be updated")

    def start_mic_stream(self):
        if self.is_running:
            print(f"Warning: stream is already running")
            return
        
        def callback(indata, outdata, frames, time, status):
            if status:
                self.status_count += 1
            
            if self.effects_chain:
                self.effects_chain.process(indata, outdata)
            else:
                outdata.fill(0)

        try:
            self.stream = sd.Stream(
                samplerate=SAMPLE_RATE,
                blocksize=BLOCKSIZE,
                dtype='float32',
                latency='low',
                channels=(CHANNELS_IN, CHANNELS_OUT),
                callback=callback,
                prime_output_buffers_using_stream_callback=True
            )
            self.stream.start()
            self.is_running = True
        except Exception as e:
            print(f"Error on stream start: {e}")

    def stop_stream(self):
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None
            self.is_running = False

    