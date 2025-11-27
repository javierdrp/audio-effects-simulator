import sys
import sounddevice as sd
import numpy as np
import threading
import gc
import soundfile as sf
import queue
import asyncio
import websockets as ws
import json

import audioblocks as ab


connected_client = None


def serialize_audio_data(in_frames, out_frames, sample_rate):
    """
    CPU-intensive task: concatenates numpy arrays and serializes to JSON.
    Run this in an executor to avoid blocking the asyncio event loop.
    """
    # Concatenate the list of arrays into one big contiguous array
    in_chunk = np.concatenate(in_frames)
    out_chunk = np.concatenate(out_frames)

    return json.dumps({
        "type": "plot_data",
        "input": in_chunk[:, 0].tolist(),
        "output": out_chunk[:, 0].tolist(),
        "sample_rate": sample_rate
    })


async def data_sender(websocket, data_queues: dict[str, queue.Queue], audio_engine):
    loop = asyncio.get_running_loop()
    
    while True:
        try:
            in_frames = []
            out_frames = []
            
            # Drain the queue of available audio blocks
            while True:
                try:
                    in_frames.append(data_queues['input'].get_nowait())
                    out_frames.append(data_queues['output'].get_nowait())
                except queue.Empty:
                    break
            
            if len(in_frames) > 0:
                # CRITICAL FIX: Run the heavy JSON serialization in a separate thread.
                # This prevents the list conversion and JSON encoding from blocking 
                # the asyncio loop, allowing 'stop' and 'update' commands to be processed immediately.
                payload = await loop.run_in_executor(
                    None, 
                    serialize_audio_data, 
                    in_frames, 
                    out_frames, 
                    audio_engine.current_sample_rate
                )
                
                await websocket.send(payload)
                
            await asyncio.sleep(0.033) # ~30 FPS
    
        except queue.Empty:
            await asyncio.sleep(0.1)
        except ws.exceptions.ConnectionClosed:
            break


async def handler(websocket):
    # check if connection is available
    global connected_client
    if connected_client is not None:
        print("Warning: client already connected. Rejecting new connection")
        return
    
    # prepare new client connection
    connected_client = websocket
    print("Connected to frontend client")
    data_queues = {
        "input": queue.Queue(maxsize=200),
        "output": queue.Queue(maxsize=200)
    }
    audio_engine = ab.AudioEngine(data_queues)

    # start data send task
    sender_task = asyncio.create_task(data_sender(websocket, data_queues, audio_engine))

    try:
        async for message in websocket:
            try:
                cmd = json.loads(message)
                command = cmd.get("command")

                if command == "start_mic":
                    audio_engine.start_mic_stream()
                elif command == "stop":
                    audio_engine.stop_stream()
                elif command == "build_chain":
                    audio_engine.build_chain(cmd.get("config", []))
                elif command == "update_param":
                    audio_engine.update_param(
                        cmd.get("effect_id"),
                        cmd.get("param"),
                        cmd.get("value")
                    )
                elif command == "process_file":
                    asyncio.create_task(audio_engine.process_wav_file(cmd.get("contents"), websocket))

            except json.JSONDecodeError:
                print(f"Error: message is not valid JSON: {message}")
            except Exception as e:
                print(f"Error processing command: {e}")

    finally:
        audio_engine.stop_stream()
        sender_task.cancel()
        connected_client = None
        print("Disconnected from frontend client")


async def main():
    gc.disable()
    print("Audio effects server initialized on ws://localhost:8765")
    async with ws.serve(handler, "localhost", 8765, max_size = 500 * 1024 * 1024):
        await asyncio.Future()
        

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nClosing server")
        gc.enable()
