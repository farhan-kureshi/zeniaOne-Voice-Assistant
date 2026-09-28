import os
import httpx
import base64
import logging

logger = logging.getLogger(__name__)
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")

async def realtime_tts_stream(text: str, language: str = "hi-IN", speaker: str = "ritu"):
    """
    Since we need to stream PCM to Exotel, and we are fixing a missing module,
    this function fetches the full TTS from Sarvam API, and yields it as raw
    Exotel-compatible PCM (16-bit, 8000Hz, Mono).
    """
    if not SARVAM_API_KEY:
        logger.error("SARVAM_API_KEY not found!")
        return

    url = "https://api.sarvam.ai/text-to-speech"
    headers = {
        "api-subscription-key": SARVAM_API_KEY,
        "Content-Type": "application/json"
    }
    
    payload = {
        "inputs": [text],
        "target_language_code": language,
        "speaker": speaker,
        "pitch": 0,
        "pace": 1.0,
        "loudness": 1.5,
        "speech_sample_rate": 8000,
        "enable_preprocessing": True,
        "model": "bulbul:v1"
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, headers=headers, timeout=15.0)
            resp.raise_for_status()
            data = resp.json()
            
            if "audios" in data and len(data["audios"]) > 0:
                audio_base64 = data["audios"][0]
                wav_bytes = base64.b64decode(audio_base64)
                
                # Convert WAV to 16-bit 8000Hz raw PCM
                from modules.audio_utils import convert_to_exotel_pcm
                pcm_bytes = convert_to_exotel_pcm(wav_bytes)
                
                # Chunk it into 320 bytes (Exotel prefers 100ms chunks which is 1600 bytes at 16-bit 8kHz)
                # Let's use 1600 bytes per chunk
                chunk_size = 1600
                for i in range(0, len(pcm_bytes), chunk_size):
                    yield pcm_bytes[i:i + chunk_size]
            else:
                logger.error("No audios returned from Sarvam TTS")
    except Exception as e:
        logger.error(f"Error calling Sarvam TTS: {e}")
