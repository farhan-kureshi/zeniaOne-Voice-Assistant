import asyncio
from modules.sarvam_tts import realtime_tts_stream
import sys
import logging

# Fix for windows charmap encoding error
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

logging.basicConfig(level=logging.INFO)

async def generate():
    try:
        with open('test_speech.mp3', 'wb') as f:
            async for chunk in realtime_tts_stream(text='Hello, this is a voice recognition test.', language='en-IN', speaker='ritu'):
                f.write(chunk)
        print("Successfully generated test_speech.mp3")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(generate())
