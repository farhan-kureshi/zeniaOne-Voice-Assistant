import asyncio
import base64
from modules.sarvam_tts import fallback_neural_tts
from modules.audio_utils import mp3_to_mulaw
import audioop

async def test():
    print("Generating TTS...")
    mp3_bytes = await fallback_neural_tts("Hello, this is a test. I am testing the audio.", speaker="ritu")
    print(f"Generated {len(mp3_bytes)} bytes of MP3")
    
    print("Converting to mu-law...")
    mulaw_bytes = mp3_to_mulaw(mp3_bytes)
    print(f"Converted to {len(mulaw_bytes)} bytes of mu-law")
    
    # Save raw mu-law to file to check it
    with open("test_output.raw", "wb") as f:
        f.write(mulaw_bytes)
    print("Saved to test_output.raw")
    
if __name__ == "__main__":
    asyncio.run(test())
