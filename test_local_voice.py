import asyncio
import websockets
import json
import base64
import audioop
import sounddevice as sd
import numpy as np

# We mimic Twilio's Audio Format: 8000Hz, G.711 mu-law, mono
SAMPLE_RATE = 8000
CHANNELS = 1

async def main():
    # Updated URL to include company_id and agent_id for database logging!
    company_id = "6a990b403e9b17bef89acf87"
    agent_id = "6a990b403e9b17bef89acf8b"
    uri = f"ws://localhost:8001/api/v1/webhook/twilio/advanced/{company_id}/{agent_id}/media-stream"
    print(f"Connecting to {uri}...")
    
    try:
        async with websockets.connect(uri) as ws:
            print("Connected! Starting audio streams...")
            
            # Send initial Twilio start event
            await ws.send(json.dumps({
                "event": "start",
                "start": {"streamSid": "local-test-123"}
            }))

            loop = asyncio.get_running_loop()

            # Output stream for playing AI's voice
            out_stream = sd.OutputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype='int16')
            out_stream.start()

            # Callback for microphone input
            def audio_callback(indata, frames, time, status):
                if status:
                    pass # ignore overflows
                # Convert float32 microphone data to int16
                pcm_data = (indata[:, 0] * 32767).astype(np.int16).tobytes()
                # Encode int16 PCM to G.711 mu-law
                ulaw_data = audioop.lin2ulaw(pcm_data, 2)
                b64_audio = base64.b64encode(ulaw_data).decode("utf-8")
                
                # Send to WebSocket
                msg = {
                    "event": "media",
                    "streamSid": "local-test-123",
                    "media": {"payload": b64_audio}
                }
                asyncio.run_coroutine_threadsafe(ws.send(json.dumps(msg)), loop)

            # Start recording from microphone
            in_stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, callback=audio_callback)
            in_stream.start()
            
            print("\n" + "="*50)
            print(">>> MICROPHONE IS LIVE! <<<")
            print("Start speaking to Zenia! (Press Ctrl+C to stop)")
            print("="*50 + "\n")

            # Receive audio from AI and play it
            try:
                async for message in ws:
                    data = json.loads(message)
                    if data["event"] == "media":
                        b64_audio = data["media"]["payload"]
                        ulaw_data = base64.b64decode(b64_audio)
                        # Decode mu-law back to int16 PCM
                        pcm_data = audioop.ulaw2lin(ulaw_data, 2)
                        out_stream.write(np.frombuffer(pcm_data, dtype=np.int16))
                    elif data["event"] == "clear":
                        # AI got interrupted, clear playback buffer
                        out_stream.stop()
                        out_stream.start()
                    else:
                        print("Server sent:", data)
            except websockets.exceptions.ConnectionClosed:
                print("Connection closed by server.")
            finally:
                in_stream.stop()
                out_stream.stop()
    except Exception as e:
        print(f"Failed to connect or error occurred: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting...")
