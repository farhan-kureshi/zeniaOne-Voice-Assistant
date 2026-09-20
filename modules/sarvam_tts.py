"""
Sarvam AI Text-to-Speech (TTS) Module
=====================================
Real-time TTS using Sarvam SDK.
Outputs MP3 which is converted to mulaw for Twilio.
"""
import asyncio
import base64
import time
from typing import Optional, List
from dataclasses import dataclass

from sarvamai import AsyncSarvamAI
import config
from modules.sarvam_stt import SarvamRealtimeSTT  # Used by realtime_stt helper below


@dataclass
class TTSChunk:
    """Audio chunk from real-time TTS"""
    audio_data: bytes
    is_final: bool
    latency_ms: Optional[float] = None


class SarvamRealtimeTTS:
    """
    Real-time Text-to-Speech using Sarvam SDK.
    Outputs MP3 which is then converted to mulaw for Twilio.
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        language: str = "en-IN",
        speaker: str = "ritu",
        model: str = "bulbul:v3"
    ):
        self.api_key = api_key or config.SARVAM_API_KEY
        self.language = language
        self.speaker = speaker
        self.model = model
        self.client: Optional[AsyncSarvamAI] = None
        self._ws_context = None
        self.ws = None
        self._configured = False
        self._start_time: Optional[float] = None
        
    async def connect(self, max_retries: int = 3, retry_delay: float = 1.0) -> bool:
        """Establish connection to Sarvam TTS with retry logic."""
        import logging
        logger = logging.getLogger(__name__)

        # Validate speaker compatibility
        if self.model == "bulbul:v3":
            supported_speakers = {"aditya", "ritu", "ashutosh", "priya", "neha", "rahul", "pooja", "rohan", "simran", "kavya", "amit", "dev", "ishita", "shreya", "ratan", "varun", "manan", "sumit", "roopa", "kabir", "aayan", "shubh", "advait", "anand", "tanya", "tarun", "sunny", "mani", "gokul", "vijay", "shruti", "suhani", "mohit", "kavitha", "rehan", "soham", "rupali"}
            if self.speaker not in supported_speakers:
                logger.error(f"[TTS_INVALID_SPEAKER] model={self.model} speaker={self.speaker}")
                raise ValueError(f"Speaker '{self.speaker}' is not compatible with model {self.model}.")

        for attempt in range(1, max_retries + 1):
            try:
                if attempt > 1:
                    logger.info(f"TTS connection retry {attempt}/{max_retries}...")
                else:
                    logger.info(f"Connecting to Sarvam TTS...")
                    
                self._start_time = time.perf_counter()
                
                self.client = AsyncSarvamAI(api_subscription_key=self.api_key)
                
                self._ws_context = self.client.text_to_speech_streaming.connect(
                    model=self.model,
                    send_completion_event=True
                )
                
                # Add timeout for connection attempt
                self.ws = await asyncio.wait_for(
                    self._ws_context.__aenter__(),
                    timeout=5.0  # 5 second timeout for connection
                )
                
                connect_time = (time.perf_counter() - self._start_time) * 1000
                logger.info(f"Sarvam TTS connected in {connect_time:.0f}ms")
                
                # Send configuration
                await self._send_config()
                
                return True
                
            except (asyncio.TimeoutError, TimeoutError) as e:
                logger.warning(f"TTS connection timeout (attempt {attempt}/{max_retries})")
                await self._cleanup_connection()
                if attempt < max_retries:
                    await asyncio.sleep(retry_delay)
                    
            except asyncio.CancelledError as e:
                logger.warning(f"TTS connection cancelled (attempt {attempt}/{max_retries})")
                await self._cleanup_connection()
                if attempt < max_retries:
                    await asyncio.sleep(retry_delay)
                    
            except Exception as e:
                logger.error(f"Failed to connect to Sarvam TTS (attempt {attempt}/{max_retries}): {e}")
                import traceback
                traceback.print_exc()
                await self._cleanup_connection()
                if attempt < max_retries:
                    await asyncio.sleep(retry_delay)
        
        logger.error(f"TTS connection failed after {max_retries} attempts")
        return False
    
    async def _cleanup_connection(self) -> None:
        """Clean up failed connection attempt."""
        try:
            if self._ws_context:
                await self._ws_context.__aexit__(None, None, None)
        except:
            pass
        self.ws = None
        self._ws_context = None
        self.client = None
        self._configured = False
    
    def is_connected(self) -> bool:
        """Check if the WebSocket connection is active."""
        return self.ws is not None and self._ws_context is not None
    
    async def ensure_connected(self) -> bool:
        """Ensure connection is alive, reconnect if needed. ⚡ For connection pooling."""
        if self.is_connected():
            return True
        return await self.connect(max_retries=2, retry_delay=0.3)
    
    async def reconfigure(self, language: str, speaker: str = "anushka") -> None:
        """Reconfigure TTS for new language without reconnecting. ⚡ Saves ~200ms."""
        self.language = language
        self.speaker = speaker
        if self.is_connected():
            await self._send_config()

    async def _send_config(self) -> None:
        """Send TTS configuration."""
        import logging
        logger = logging.getLogger(__name__)
        if not self.ws:
            return
        
        try:
            # Configure TTS - SDK outputs MP3 by default
            # We'll convert to mulaw for Twilio
            await self.ws.configure(
                target_language_code=self.language,
                speaker=self.speaker,
                pitch=0.0,
                pace=1.0
            )
            self._configured = True
            logger.info(f"TTS configured: {self.language}, {self.speaker}")
        except Exception as e:
            logger.error(f"Error configuring TTS: {e}")
            import traceback
            traceback.print_exc()
    
    async def send_text(self, text: str) -> None:
        """Send text to be synthesized."""
        import logging
        logger = logging.getLogger(__name__)
        if not self.ws or not self._configured:
            logger.warning("TTS not connected or configured")
            return
        
        try:
            # Send text chunks
            logger.info(f"Sending {len(text)} chars to TTS...")
            await self.ws.convert(text)
        except Exception as e:
            logger.error(f"Error sending text to TTS: {e}")
    
    async def flush(self) -> None:
        """Send flush signal to indicate end of text."""
        import logging
        logger = logging.getLogger(__name__)
        if not self.ws:
            return
            
        try:
            await self.ws.flush()
            logger.info("TTS flush signal sent")
        except Exception as e:
            logger.error(f"Error sending flush: {e}")
    
    async def receive_all(self, max_wait: float = 10.0) -> List[bytes]:
        """
        Receive all audio chunks until completion.
        Returns list of raw audio bytes (mp3 format from SDK).
        """
        import logging
        logger = logging.getLogger(__name__)
        if not self.ws:
            return []
        
        audio_chunks = []
        chunk_count = 0
        
        try:
            logger.info("Receiving TTS audio chunks...")
            
            async for message in self.ws:
                msg_type = getattr(message, 'type', None)
                
                # Check for explicit error from server
                if msg_type == 'error':
                    error_msg = getattr(message.data, 'message', 'Unknown TTS Error') if hasattr(message, 'data') else 'Unknown TTS Error'
                    logger.error(f"[TTS_RECEIVE_ERROR] Server returned error: {error_msg}")
                    raise RuntimeError(f"Sarvam TTS Error: {error_msg}")
                    
                # Check if it's an AudioOutput object
                if hasattr(message, 'data') and hasattr(message.data, 'audio'):
                    audio_b64 = message.data.audio
                    audio_data = base64.b64decode(audio_b64)
                    audio_chunks.append(audio_data)
                    chunk_count += 1
                    logger.info(f"Audio chunk {chunk_count}: {len(audio_data)} bytes")
                
                # Check for completion event
                elif hasattr(message, 'data') and hasattr(message.data, 'event_type'):
                    if message.data.event_type == "final":
                        logger.info("TTS generation complete")
                        break
                
                # Handle dict responses
                elif isinstance(message, dict):
                    if message.get("type") == "error":
                        error_msg = message.get("data", {}).get("message", "Unknown TTS Error")
                        logger.error(f"[TTS_RECEIVE_ERROR] Server returned error: {error_msg}")
                        raise RuntimeError(f"Sarvam TTS Error: {error_msg}")
                    elif "audio" in message:
                        audio_data = base64.b64decode(message["audio"])
                        audio_chunks.append(audio_data)
                        chunk_count += 1
                    elif message.get("event_type") == "final" or message.get("type") == "event":
                        break
            
            logger.info(f"Total TTS chunks received: {chunk_count}")
            if chunk_count == 0:
                logger.warning("TTS completed but zero audio chunks were received.")
                
            return audio_chunks
            
        except Exception as e:
            logger.error(f"Error receiving TTS: {e}")
            raise  # Re-raise so the caller knows TTS failed
    
    async def receive_stream(self):
        """
        Yield audio chunks as they arrive from the WebSocket.
        """
        if not self.ws:
            return

        chunk_count = 0
        try:
            print("⏳ Streaming TTS audio chunks...")

            async for message in self.ws:
                # Check if it's an AudioOutput object
                if hasattr(message, 'data') and hasattr(message.data, 'audio'):
                    audio_b64 = message.data.audio
                    audio_data = base64.b64decode(audio_b64)
                    yield audio_data
                    chunk_count += 1

                # Check for completion event
                elif hasattr(message, 'data') and hasattr(message.data, 'event_type'):
                    if message.data.event_type == "final":
                        # print("✅ TTS generation complete")
                        break
                
                # Handle dict responses
                elif isinstance(message, dict):
                    if "audio" in message:
                        audio_data = base64.b64decode(message["audio"])
                        yield audio_data
                        chunk_count += 1
                    elif message.get("event_type") == "final":
                        break
            
            print(f"📊 Total streaming TTS chunks received: {chunk_count}")

        except Exception as e:
            print(f"❌ Error receiving TTS stream: {e}")
            import traceback
            traceback.print_exc()

    async def ping(self) -> bool:
        """Send ping to keep connection alive. Returns True if connection is healthy."""
        if not self.ws:
            return False
        try:
            # Sarvam TTS supports ping signal
            await self.ws.ping()
            return True
        except Exception as e:
            print(f"⚠️ TTS ping failed: {e}")
            return False
    
    async def reset_for_stream(self) -> None:
        """Reset state for a new TTS stream without disconnecting. ⚡ Saves ~1s per turn."""
        self._start_time = time.perf_counter()
        # Connection stays open, just reset timing
        # No need to reconfigure unless language changes

    async def disconnect(self) -> None:
        """Close connection."""
        if self._ws_context:
            try:
                await self._ws_context.__aexit__(None, None, None)
                print("🔌 Sarvam TTS disconnected")
            except:
                pass
        self.ws = None
        self._ws_context = None
        self.client = None
        self._configured = False


# Global connection pools
_stt_pool = {}
_tts_pool = {}

async def _get_pooled_stt(language: str, max_retries: int) -> SarvamRealtimeSTT:
    pool_key = language
    stt = _stt_pool.get(pool_key)
    if stt and stt.is_connected():
        await stt.reset_for_new_turn()
        return stt
    
    stt = SarvamRealtimeSTT(language=language)
    if not await stt.connect(max_retries=max_retries):
        return None
    _stt_pool[pool_key] = stt
    return stt

async def realtime_stt(audio_data: bytes, language: str = "hi-IN", max_retries: int = 3, encoding: str = "audio/wav") -> str:
    """Convenience function for a single voice turn with connection pooling."""
    stt = await _get_pooled_stt(language, max_retries)
    if not stt:
        return ""
    try:
        await stt.send_audio(audio_data, encoding=encoding)
        await stt.flush()
        result = await stt.receive()
        return result.transcript if result else ""
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Pooled STT error: {e}")
        await stt.disconnect()
        _stt_pool.pop(language, None)
        return ""

async def _acquire_tts(language: str, speaker: str) -> 'SarvamRealtimeTTS':
    import logging
    logger = logging.getLogger(__name__)
    pool_key = f"{language}_{speaker}"
    
    tts = _tts_pool.pop(pool_key, None)
    
    if tts and tts.is_connected():
        logger.info(f"[VOICE_TTS_POOL_REUSE] key={pool_key}")
        await tts.reset_for_stream()
        return tts
    
    if tts:
        await tts.disconnect()
        
    logger.info(f"[VOICE_TTS_POOL_CREATE] key={pool_key}")
    tts = SarvamRealtimeTTS(language=language, speaker=speaker)
    if not await tts.connect():
        logger.error(f"[VOICE_TTS_POOL_ERROR] key={pool_key}")
        return None
    return tts

def _release_tts(language: str, speaker: str, tts: 'SarvamRealtimeTTS'):
    if tts and tts.is_connected():
        _tts_pool[f"{language}_{speaker}"] = tts

async def realtime_tts(
    text: str,
    language: str = "en-IN",
    speaker: str = "anushka"
) -> bytes:
    """Synthesize speech - returns raw audio (mp3) with connection pooling."""
    import logging
    logger = logging.getLogger(__name__)
    pool_key = f"{language}_{speaker}"
    
    for attempt in range(2):
        tts = await _acquire_tts(language, speaker)
        if not tts:
            if attempt == 1:
                logger.error(f"[VOICE_TTS_POOL_RECOVERY_FAILED] key={pool_key}")
            return b""
            
        try:
            await tts.send_text(text)
            await tts.flush()
            chunks = await tts.receive_all()
            _release_tts(language, speaker, tts)
            if attempt == 1:
                logger.info(f"[VOICE_TTS_POOL_RECOVERY_SUCCESS] key={pool_key}")
            return b"".join(chunks)
        except Exception as e:
            logger.warning(f"Pooled TTS error (attempt {attempt+1}): {e}")
            await tts.disconnect()
            if attempt == 0:
                logger.info(f"[VOICE_TTS_POOL_STALE] key={pool_key}")
                logger.info(f"[VOICE_TTS_POOL_RECREATE] Retrying request")
            else:
                logger.error(f"[VOICE_TTS_POOL_RECOVERY_FAILED] key={pool_key}")
                return b""
                
    return b""

async def realtime_tts_stream(
    text: str,
    language: str = "en-IN",
    speaker: str = "anushka"
):
    """Synthesize speech - yields raw audio chunks (linear16 24kHz) with connection pooling."""
    import logging
    logger = logging.getLogger(__name__)
    pool_key = f"{language}_{speaker}"
    
    for attempt in range(2):
        tts = await _acquire_tts(language, speaker)
        if not tts:
            if attempt == 1:
                logger.error(f"[VOICE_TTS_POOL_RECOVERY_FAILED] key={pool_key}")
            return
            
        chunks_yielded = 0
        try:
            # Reconfigure for linear16 streaming
            await tts.ws.configure(
                target_language_code=language,
                speaker=speaker,
                output_audio_codec="linear16",
                speech_sample_rate=24000
            )
            
            await tts.send_text(text)
            await tts.flush()
            
            async for chunk in tts.receive_stream():
                yield chunk
                chunks_yielded += 1
                
            _release_tts(language, speaker, tts)
            if attempt == 1:
                logger.info(f"[VOICE_TTS_POOL_RECOVERY_SUCCESS] key={pool_key}")
            return
                
        except Exception as e:
            logger.warning(f"Pooled TTS stream error (attempt {attempt+1}): {e}")
            await tts.disconnect()
            if chunks_yielded > 0:
                logger.error(f"[VOICE_TTS_POOL_RECOVERY_FAILED] key={pool_key} - Cannot retry, partial audio emitted")
                return
            if attempt == 0:
                logger.info(f"[VOICE_TTS_POOL_STALE] key={pool_key}")
                logger.info(f"[VOICE_TTS_POOL_RECREATE] Retrying request")
            else:
                logger.error(f"[VOICE_TTS_POOL_RECOVERY_FAILED] key={pool_key}")
                return
