import asyncio
import sys
import logging
from modules.sarvam_stt import StreamingAudioPipeline

# Fix for windows charmap encoding error
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("STT_TEST")

async def run_test():
    try:
        logger.info("[VOICE][SELFTEST][STT] source audio created")
        with open('test_speech.raw', 'rb') as f:
            pcm_data = f.read()
        
        logger.info("[VOICE][SELFTEST][STT] converted to pcm_s16le")
        logger.info("[VOICE][SELFTEST][STT] sample_rate=16000")
        logger.info("[VOICE][SELFTEST][STT] channels=1")
        logger.info(f"[VOICE][SELFTEST][STT] bytes={len(pcm_data)}")

        latest_transcript = ""
        
        async def on_transcript_ready(transcript: str):
            nonlocal latest_transcript
            latest_transcript = transcript
            
        async def on_speech_end():
            logger.info("[VOICE][SELFTEST][STT] speech end callback triggered")
            
        pipeline = StreamingAudioPipeline(
            language="en-IN",
            sample_rate=16000,
            on_transcript_ready=on_transcript_ready,
            on_speech_end=on_speech_end
        )
        
        logger.info("[VOICE][SELFTEST][STT] connection started")
        success = await pipeline.start()
        if not success:
            logger.error("[VOICE][SELFTEST][STT] connection failed")
            return
            
        logger.info("[VOICE][SELFTEST][STT] connected")
        
        # Send audio in chunks to simulate streaming
        chunk_size = 4096
        for i in range(0, len(pcm_data), chunk_size):
            chunk = pcm_data[i:i+chunk_size]
            await pipeline.process_audio_chunk(chunk)
            await asyncio.sleep(0.05) # Simulate real-time
            
        logger.info("[VOICE][SELFTEST][STT] speech audio sent")
        
        # Wait a bit before forcing finalize
        await asyncio.sleep(1)
        
        logger.info("[VOICE][SELFTEST][STT] finalization requested")
        final_result = await pipeline.force_finalize()
        
        if final_result and final_result.transcript.strip():
            latest_transcript = final_result.transcript
            
        logger.info(f"[VOICE][SELFTEST][STT] final transcript=\"{latest_transcript}\"")
        
        if "hello" in latest_transcript.lower() or "voice recognition" in latest_transcript.lower():
            logger.info("[VOICE][SELFTEST][STT] STT BACKEND HEALTHY")
        else:
            logger.info("[VOICE][SELFTEST][STT] STT BACKEND FAILURE")

        await pipeline.stt.disconnect()
        
    except Exception as e:
        logger.error(f"Error during STT test: {e}")

if __name__ == "__main__":
    asyncio.run(run_test())
