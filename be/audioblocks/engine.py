from __future__ import annotations
import json
import queue
import sounddevice as sd
import sys
import base64
import io
import numpy as np
import soundfile as sf
import scipy.io

import audioblocks as ab


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
        self.last_chain_config = []
        self.is_processing_file = False
        self.status_count = 0

    def build_chain(self, effects_config: list[dict]):
        self.last_chain_config = effects_config
        chain = ab.EffectsChain(SAMPLE_RATE, CHANNELS_IN, CHANNELS_OUT, BLOCKSIZE)
        self.effects_map.clear()

        chain.add(ab.PlotDataTap(self.data_queues['input']))

        for config in effects_config:
            effect_id = config.get('id')
            effect_type = config.get('type')
            params = config.get('params', {})

            if effect_type == 'delay': fx = ab.StereoDelayEffect(**params)
            elif effect_type == 'reverb': fx = ab.ReverbEffect(**params)
            #  add other effects here
            else: continue
            chain.add(fx)

            if effect_id:
                self.effects_map[effect_id] = fx

        chain.add(ab.PlotDataTap(self.data_queues['output']))

        chain.warmup()
        self.effects_chain = chain

    async def process_wav_file(self, contents, websocket):
        if self.is_processing_file:
            print("Warning. A file is already being process. Ignoring new request")
            return
        
        self.is_processing_file = True
        try:
            content_type, content_string = contents.split(',')
            decoded_bytes = base64.b64decode(content_string)

            with io.BytesIO(decoded_bytes) as wav_io:
                audio_data, fs = sf.read(wav_io, dtype='float32')

            if audio_data.ndim > 1:
                audio_data_mono = audio_data.mean(axis=1, keepdims=True)
            else:
                audio_data_mono = audio_data.reshape(-1, 1)

            ch_in, ch_out = 1, 2
            file_blocksize = 1024
            chain = ab.EffectsChain(fs, ch_in, ch_out, file_blocksize)
            for config in self.last_chain_config:
                effect_type, params = config.get('type'), config.get('params', {})
                if effect_type == "delay":
                    fx = ab.StereoDelayEffect(**params)
                elif effect_type == "reverb":
                    fx = ab.ReverbEffect(**params)
                else: continue
                chain.add(fx)
            chain.warmup()

            processed_audio = np.zeros((len(audio_data_mono), ch_out), dtype=np.float32)
            chain.process(audio_data_mono, processed_audio)

            processed_audio = np.clip(processed_audio, -1.0, 1.0)
            processed_int16 = (processed_audio * 32767).astype(np.int16)

            with io.BytesIO() as out_io:
                scipy.io.wavfile.write(out_io, fs, processed_int16)
                out_io.seek(0)
                processed_b64_bytes = base64.b64encode(out_io.read())

            processed_b64_string = processed_b64_bytes.decode('ascii')
            processed_data_url = f"data:audio/wav;base64,{processed_b64_string}"

            response = {
                'type': 'file_processed',
                'original_b64': contents,
                'processed_b64': processed_data_url,
                'sample_rate': fs,
                'original_samples': audio_data_mono.flatten().tolist(),
                'processed_samples': processed_audio.mean(axis=1).flatten().tolist()
            }
            await websocket.send(json.dumps(response))
        
        except Exception as e:
            print(f"Error processing WAV file: {e}")
        finally:
            self.is_processing_file = False

    def update_param(self, effect_id: str, param_name: str, value: float):
        if effect_id not in self.effects_map:
            print(f"Error: effect ID '{effect_id}' not found")
            return
        
        effect = self.effects_map[effect_id]

        # update using setter or SmoothParam
        setter_func = f"set_{param_name}"
        if hasattr(effect, setter_func):
            getattr(effect, setter_func)(value)
        elif hasattr(effect, param_name) and isinstance((att := getattr(effect, param_name)), ab.SmoothParam):
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

    