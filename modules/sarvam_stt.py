"""
Sarvam AI Speech-to-Text (STT) Module
=====================================
Contains both streaming and batch STT implementations:

1. TrueStreamingSTT - Real-time streaming STT (primary)
   - Audio chunks streamed immediately as they arrive
   - VAD signals for end-of-speech detection
   - Sub-500ms latency
   
2. SarvamRealtimeSTT - Batch STT (fallback)
   - Send complete audio, get transcript
   - Used when streaming fails
"""
import asyncio
import base64
import time
from typing import Optional, Callable, Any
from dataclasses import dataclass, field

from sarvamai import AsyncSarvamAI
import config


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class STTResult:
    """Result from batch STT (SarvamRealtimeSTT)"""
    transcript: str
    is_final: bool
    language_code: Optional[str] = None
    latency_ms: Optional[float] = None


@dataclass
class StreamingSTTResult:
    """Result from streaming STT"""
    transcript: str
    is_final: bool
    language_code: Optional[str] = None
    latency_ms: Optional[float] = None  # Processing latency (flush → transcript)
    total_latency_ms: Optional[float] = None  # Total time (first chunk → transcript)
    vad_event: Optional[str] = None  # START_SPEECH, END_SPEECH
    turn_id: Optional[int] = None  # Turn ID this result belongs to


@dataclass 
class StreamingState:
    """State for streaming STT session"""
    is_connected: bool = False
    is_listening: bool = False
    is_reconnecting: bool = False
    reconnect_attempts: int = 0
    speech_started: bool = False
    speech_ended: bool = False
    current_transcript: str = ""
    final_transcript: str = ""
    audio_chunks_sent: int = 0
    total_audio_bytes: int = 0
    start_time: float = field(default_factory=time.perf_counter)
    first_audio_time: Optional[float] = None
    end_speech_time: Optional[float] = None
    accumulated_pcm: bytes = b""  # Accumulate PCM locally, send as one WAV before flush


class TrueStreamingSTT:
    """
    True real-time streaming STT using Sarvam AI.
    
    Usage:
        stt = TrueStreamingSTT(language="en-IN")
        await stt.connect()
        
        # Start background listener
        await stt.start_listening(on_transcript=my_callback)
        
        # Stream audio chunks as they arrive
        for chunk in audio_chunks:
            await stt.stream_chunk(chunk)
        
        # Get final transcript after END_SPEECH
        transcript = await stt.get_final_transcript()
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        language: str = "unknown",  # Auto-detect by default
        model: str = "saarika:v2.5",
        sample_rate: int = 16000
    ):
        self.api_key = api_key or config.SARVAM_API_KEY
        self.language = language
        self.model = model
        self.sample_rate = sample_rate
        
        self.client: Optional[AsyncSarvamAI] = None
        self._ws_context = None
        self.ws = None
        
        self.state = StreamingState()
        self._listener_task: Optional[asyncio.Task] = None
        self._reconnect_task: Optional[asyncio.Task] = None
        self._intentional_disconnect: bool = False
        self._transcript_ready = asyncio.Event()
        self._on_transcript: Optional[Callable] = None
        self._on_vad_event: Optional[Callable] = None
        
        # Turn tracking for stale event detection
        self._current_turn_id: int = 0  # Increments each turn (starts at 0 for first turn)
        self._transcript_turn_id: int = -1  # Turn ID when transcript was received (-1 = none)
        self._vad_turn_id: int = -1  # Turn ID when VAD event was received (-1 = none)
        
    async def connect(self, max_retries: int = 2, retry_delay: float = 0.3) -> bool:
        """
        Establish streaming connection to Sarvam STT.
        Connection is kept open for the entire call duration.
        """
        for attempt in range(1, max_retries + 1):
            try:
                if attempt > 1:
                    print(f"🔄 Streaming STT retry {attempt}/{max_retries}...")
                else:
                    print(f"🎙️ Connecting to Sarvam Streaming STT...")
                
                self.state = StreamingState()
                self.state.start_time = time.perf_counter()
                self._intentional_disconnect = False
                
                # Reset turn tracking on new connection
                self._current_turn_id = 0
                self._transcript_turn_id = -1
                self._vad_turn_id = -1
                
                self.client = AsyncSarvamAI(api_subscription_key=self.api_key)
                
                # Configure for streaming:
                # - vad_signals=true: Get START_SPEECH/END_SPEECH events
                # - flush_signal=true: Can manually flush for final transcript
                # - high_vad_sensitivity=false: Reduce premature cutoffs
                # NOTE: SDK transcribe() only accepts audio/wav, so we wrap PCM in WAV headers
                
                connect_kwargs = {
                    "language_code": self.language,
                    "model": self.model,
                    "sample_rate": str(self.sample_rate),
                    "input_audio_codec": "pcm_s16le", # Tell server to expect raw PCM
                    "high_vad_sensitivity": "false",
                    "vad_signals": "true",
                    "flush_signal": "true"
                }
                
                self._ws_context = self.client.speech_to_text_streaming.connect(**connect_kwargs)
                
                self.ws = await asyncio.wait_for(
                    self._ws_context.__aenter__(),
                    timeout=5.0
                )
                
                connect_time = (time.perf_counter() - self.state.start_time) * 1000
                print(f"✅ Streaming STT connected in {connect_time:.0f}ms")
                
                self.state.is_connected = True
                return True
                
            except asyncio.TimeoutError:
                print(f"⏰ Streaming STT timeout (attempt {attempt}/{max_retries})")
                await self._cleanup()
                if attempt < max_retries:
                    await asyncio.sleep(retry_delay)
                    
            except Exception as e:
                print(f"❌ Streaming STT connection failed: {e}")
                await self._cleanup()
                if attempt < max_retries:
                    await asyncio.sleep(retry_delay)
        
        return False
    
    async def _cleanup(self):
        """Clean up connection resources."""
        try:
            if self._listener_task and not self._listener_task.done():
                self._listener_task.cancel()
                try:
                    await self._listener_task
                except asyncio.CancelledError:
                    pass
            if self._ws_context:
                await self._ws_context.__aexit__(None, None, None)
        except:
            pass
        self.ws = None
        self._ws_context = None
        self.client = None
        self.state.is_connected = False
        self.state.is_listening = False
    
    async def start_listening(
        self, 
        on_transcript: Optional[Callable[[str, bool], Any]] = None,
        on_vad_event: Optional[Callable[[str, int], Any]] = None  # Now includes turn_id
    ):
        """
        Start background listener for STT results.
        
        Args:
            on_transcript: Callback(transcript, is_final) for transcript updates
            on_vad_event: Callback(event_type, turn_id) for VAD events - turn_id allows validation
        """
        if not self.ws:
            print("⚠️ Cannot start listening - not connected")
            return
        
        self._on_transcript = on_transcript
        self._on_vad_event = on_vad_event
        self.state.is_listening = True
        self._transcript_ready.clear()
        
        self._listener_task = asyncio.create_task(self._background_listener())
    
    async def _background_listener(self):
        """Background task that listens for STT messages with turn tracking."""
        if not self.ws:
            return
        
        print(f"  🎧 [VOICE_STT_LISTENER_STARTED] Background listener started (turn_id={self._current_turn_id})")
            
        try:
            async for message in self.ws:
                msg_type = getattr(message, 'type', None)
                msg_data = getattr(message, 'data', None)
                
                # Dump raw response for diagnostics
                keys = []
                if msg_data:
                    keys = [k for k in dir(msg_data) if not k.startswith('_')]
                elif isinstance(message, dict):
                    msg_type = message.get('type')
                    keys = list(message.keys())
                
                print(f"  [VOICE_STT_RAW_RESPONSE] type={msg_type} keys={keys}")
                
                # Capture turn_id at time of receiving message
                received_turn_id = self._current_turn_id
                
                if msg_type == 'events':
                    signal = getattr(msg_data, 'signal_type', None) if msg_data else None
                    
                    if signal == 'START_SPEECH':
                        self.state.speech_started = True
                        self._vad_turn_id = received_turn_id  # Tag with current turn
                        print(f"  🎤 [VAD] Speech started (turn_id={received_turn_id})")
                        if self._on_vad_event:
                            # Pass turn_id so caller can validate
                            await self._safe_callback(self._on_vad_event, signal, received_turn_id)
                            
                    elif signal == 'END_SPEECH':
                        self.state.speech_ended = True
                        self.state.end_speech_time = time.perf_counter()
                        self._vad_turn_id = received_turn_id  # Tag with current turn
                        print(f"  🔇 [VAD] Speech ended (turn_id={received_turn_id}, current={self._current_turn_id})")
                        if self._on_vad_event:
                            # Pass turn_id so caller can validate
                            await self._safe_callback(self._on_vad_event, signal, received_turn_id)
                        # Note: Don't auto-flush here - let process_speech_streaming handle it
                        # This prevents double-flush issues
                        
                elif msg_type == 'data':
                    transcript = getattr(msg_data, 'transcript', '') if msg_data else ''
                    language = getattr(msg_data, 'language_code', self.language) if msg_data else self.language
                    
                    # Tag transcript with current turn
                    self._transcript_turn_id = received_turn_id
                    
                    self.state.current_transcript = transcript
                    self.state.final_transcript = transcript
                    
                    latency_ms = None
                    if self.state.first_audio_time:
                        latency_ms = (time.perf_counter() - self.state.first_audio_time) * 1000
                    
                    if transcript.strip():
                        is_final_msg = getattr(msg_data, 'is_final', False)
                        log_tag = "[VOICE_STT_FINAL]" if is_final_msg else "[VOICE_STT_PARTIAL]"
                        print(f"  📝 {log_tag} Transcript (turn={received_turn_id}): '{transcript[:50]}{'...' if len(transcript) > 50 else ''}' (latency: {latency_ms:.0f}ms)" if latency_ms else f"  📝 {log_tag} Transcript (turn={received_turn_id}): '{transcript[:50]}{'...' if len(transcript) > 50 else ''}'")
                    
                    # Update language from detection
                    if language and language != "unknown":
                        self.language = language
                    
                    if self._on_transcript:
                        await self._safe_callback(self._on_transcript, transcript, True)
                    
                    # Signal that transcript is ready
                    self._transcript_ready.set()
                    
        except asyncio.CancelledError:
            print(f"  🛑 [VOICE_STT_LISTENER_CLOSED] Background listener cancelled")
            pass
        except Exception as e:
            print(f"  ❌ [VOICE_STT_RESPONSE_ERROR] Background listener error: {e}")
            import traceback
            traceback.print_exc()
            self.state.is_listening = False
            self.state.is_connected = False
            self.state.is_reconnecting = True
        finally:
            print("  🔌 [STT] Listener stopped")
    
    async def _safe_callback(self, callback, *args):
        """Safely execute callback (sync or async)."""
        try:
            result = callback(*args)
            if asyncio.iscoroutine(result):
                await result
        except Exception as e:
            print(f"⚠️ Callback error: {e}")
    
    def _pcm_to_wav_bytes(self, pcm_data: bytes) -> bytes:
        """
        Convert PCM to WAV format in memory (minimal overhead).
        This is required because Sarvam SDK only accepts audio/wav encoding.
        """
        import struct
        import io
        
        # WAV header parameters
        channels = 1
        sample_width = 2  # 16-bit
        byte_rate = self.sample_rate * channels * sample_width
        block_align = channels * sample_width
        data_size = len(pcm_data)
        file_size = 36 + data_size
        
        # Build WAV header (44 bytes)
        header = struct.pack(
            '<4sI4s4sIHHIIHH4sI',
            b'RIFF',
            file_size,
            b'WAVE',
            b'fmt ',
            16,  # Subchunk1Size for PCM
            1,   # AudioFormat (1 = PCM)
            channels,
            self.sample_rate,
            byte_rate,
            block_align,
            sample_width * 8,  # BitsPerSample
            b'data',
            data_size
        )
        
        return header + pcm_data
    
    async def stream_chunk(self, pcm_chunk: bytes) -> None:
        """
        Accumulate audio chunk for later sending.
        Audio is accumulated locally and sent as ONE complete WAV before flush.
        This keeps connection persistent while using the format Sarvam expects.
        
        Args:
            pcm_chunk: PCM 16-bit audio at configured sample rate
        """
        if self.state.is_reconnecting:
            # Buffer audio during reconnect
            self.state.accumulated_pcm += pcm_chunk
            if len(self.state.accumulated_pcm) > 64000: # bounded 2s buffer
                self.state.accumulated_pcm = self.state.accumulated_pcm[-64000:]
            
            if self.state.reconnect_attempts < 2:
                if getattr(self, '_reconnect_task', None) and not self._reconnect_task.done():
                    return
                
                self.state.reconnect_attempts += 1
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"[VOICE_STT_RECONNECT_START] attempt={self.state.reconnect_attempts}")
                
                # Attempt reconnect in background
                async def do_reconnect():
                    logger.info("[VOICE_STT_RECONNECT_TASK_START]")
                    try:
                        success = await self.connect(max_retries=1)
                        if success:
                            if getattr(self, '_intentional_disconnect', False):
                                logger.info("[VOICE_STT_RECONNECT_TASK_ABORTED]")
                                await self._cleanup()
                                return
                            logger.info("[VOICE_STT_RECONNECT_SUCCESS] latency_ms=0")
                            await self.start_listening(on_transcript=self._on_transcript, on_vad_event=self._on_vad_event)
                            self.state.is_reconnecting = False
                            self.state.reconnect_attempts = 0
                        else:
                            logger.error(f"[VOICE_STT_RECONNECT_FAILED] attempt={self.state.reconnect_attempts}")
                    except asyncio.CancelledError:
                        logger.info("[VOICE_STT_RECONNECT_TASK_CANCEL]")
                        raise
                    except Exception as e:
                        logger.error(f"[VOICE_STT_RECONNECT_FAILED] err={e}")
                    finally:
                        logger.info("[VOICE_STT_RECONNECT_TASK_COMPLETE]")
                        if getattr(self, '_reconnect_task', None) and self._reconnect_task.done():
                            self._reconnect_task = None
                
                self._reconnect_task = asyncio.create_task(do_reconnect())
            return
            
        if not self.ws or not self.state.is_connected:
            return
        
        # Track first audio time for latency measurement
        if self.state.first_audio_time is None:
            self.state.first_audio_time = time.perf_counter()
        
        # We must keep accumulating for fallback or final flush if needed
        self.state.accumulated_pcm += pcm_chunk
        self.state.audio_chunks_sent += 1
        self.state.total_audio_bytes += len(pcm_chunk)
        
        try:
            # Send RAW PCM chunk directly (no WAV header)
            pcm_b64 = base64.b64encode(pcm_chunk).decode('utf-8')
            
            # Note: We must pass encoding="audio/wav" to satisfy the SDK's local Pydantic validation,
            # but the server knows it's PCM because we passed input_audio_codec="pcm_s16le" in connect()
            await self.ws.transcribe(
                audio=pcm_b64,
                encoding="audio/wav",
                sample_rate=self.sample_rate
            )
            
            if not hasattr(self, '_stt_forward_log_time'):
                self._stt_forward_log_time = 0
                self._stt_forward_log_count = 0
                
            now = time.time()
            if self._stt_forward_log_count < 3 or now - self._stt_forward_log_time > 2.0:
                print(f"  [VOICE_STT_SEND] bytes={len(pcm_chunk)} format=pcm_s16le turn_id={self._current_turn_id}")
                self._stt_forward_log_count += 1
                self._stt_forward_log_time = now
                
        except Exception as e:
            print(f"⚠️ Error forwarding chunk to STT: {e}")
    
    async def _send_accumulated_audio(self) -> bool:
        """Send all accumulated audio as ONE complete WAV file."""
        if not self.ws or not self.state.accumulated_pcm:
            return False
        
        try:
            # Convert accumulated PCM to single WAV
            wav_audio = self._pcm_to_wav_bytes(self.state.accumulated_pcm)
            wav_b64 = base64.b64encode(wav_audio).decode('utf-8')
            
            audio_duration = len(self.state.accumulated_pcm) / 2 / self.sample_rate
            print(f"  📤 [STT] Sending {audio_duration:.1f}s audio as single WAV ({len(wav_audio)} bytes)")
            
            # Send complete audio to STT
            await self.ws.transcribe(
                audio=wav_b64,
                encoding="audio/wav",
                sample_rate=self.sample_rate
            )
            return True
            
        except Exception as e:
            print(f"⚠️ Error sending accumulated audio: {e}")
            return False
    
    async def flush(self) -> None:
        """Send accumulated audio then flush signal to finalize transcription.
        Also clears stale transcript state to ensure we wait for fresh result."""
        if not self.ws:
            return
        try:
            # Clear stale transcript state BEFORE sending new audio
            # This ensures get_final_transcript waits for the NEW transcript
            self._transcript_ready.clear()
            self.state.final_transcript = ""
            self._transcript_turn_id = -1  # Mark as no valid transcript yet
            
            self._flush_time = time.perf_counter()  # Track when flush was sent
            await self.ws.flush()
        except Exception as e:
            print(f"⚠️ Flush error: {e}")
    
    async def get_final_transcript(self, timeout: float = 4.0) -> StreamingSTTResult:
        """
        Wait for and return the final transcript.
        Call this after END_SPEECH is detected or after manually flushing.
        
        This method validates that the transcript is from the CURRENT turn,
        ignoring stale transcripts from previous turns.
        
        Args:
            timeout: Maximum time to wait for transcript
            
        Returns:
            StreamingSTTResult with final transcript
        """
        expected_turn = self._current_turn_id
        deadline = time.perf_counter() + timeout
        
        while True:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                print(f"  ⏰ [STT] Transcript timeout after {timeout}s (turn_id={expected_turn})")
                break
            
            try:
                await asyncio.wait_for(self._transcript_ready.wait(), remaining)
            except asyncio.TimeoutError:
                print(f"⏰ Transcript timeout after {timeout}s")
                break
            
            # Check if transcript is for THIS turn
            if self._transcript_turn_id == expected_turn:
                # Valid transcript for current turn
                break
            elif self._transcript_turn_id == -1:
                # No transcript yet (cleared state), keep waiting
                self._transcript_ready.clear()
                continue
            else:
                # Stale transcript from previous turn - ignore and wait again
                print(f"  ⚠️ [STT] Ignoring stale transcript (received turn={self._transcript_turn_id}, expected={expected_turn})")
                self._transcript_ready.clear()
                self.state.final_transcript = ""  # Clear stale transcript
                continue
        
        # Calculate actual processing latency (from flush to transcript)
        processing_latency_ms = None
        if hasattr(self, '_flush_time'):
            processing_latency_ms = (time.perf_counter() - self._flush_time) * 1000
        
        # Also track total latency from first audio (for reference)
        total_latency_ms = None
        if self.state.first_audio_time:
            total_latency_ms = (time.perf_counter() - self.state.first_audio_time) * 1000
        
        return StreamingSTTResult(
            transcript=self.state.final_transcript,
            is_final=True,
            language_code=self.language,
            latency_ms=processing_latency_ms,  # Actual processing time (~100-200ms)
            total_latency_ms=total_latency_ms,  # Full duration for reference
            turn_id=self._transcript_turn_id  # Include turn_id for reference
        )
    
    async def reset_for_new_turn(self) -> None:
        """
        Reset state for a new turn without disconnecting.
        This allows reusing the same WebSocket connection across turns.
        
        IMPORTANT: Increments turn_id FIRST to invalidate any pending
        stale transcripts or VAD events from the previous turn.
        """
        # Increment turn counter FIRST - this invalidates any pending stale events
        old_turn_id = self._current_turn_id
        self._current_turn_id += 1
        
        # Check if listener is healthy
        listener_alive = self._listener_task is not None and not self._listener_task.done()
        
        # Reset state but keep connection
        old_chunks = self.state.audio_chunks_sent
        self.state = StreamingState()
        self.state.is_connected = self.ws is not None
        self.state.is_listening = listener_alive
        
        # Clear transcript tracking for new turn
        self._transcript_ready.clear()
        self._transcript_turn_id = -1  # No valid transcript for new turn yet
        self._vad_turn_id = -1  # No valid VAD for new turn yet
        
        # Clear flush time to avoid stale latency calculations
        if hasattr(self, '_flush_time'):
            delattr(self, '_flush_time')
        
        print(f"  🔄 [STT] Reset for turn {self._current_turn_id} (was turn {old_turn_id}, {old_chunks} chunks, listener: {'alive' if listener_alive else 'dead'})")
        
        # If listener died, restart it
        if not listener_alive and self.ws:
            print("  🔄 [STT] Restarting listener...")
            await self.start_listening(self._on_transcript, self._on_vad_event)
    
    def is_healthy(self) -> bool:
        """Check if the streaming STT is in a healthy state."""
        ws_ok = self.ws is not None
        listener_ok = self._listener_task is not None and not self._listener_task.done()
        return ws_ok and listener_ok
    
    def is_vad_event_valid(self) -> bool:
        """
        Check if the most recent VAD event is from the current turn.
        
        Use this to validate VAD events before acting on them,
        preventing stale END_SPEECH events from triggering processing.
        
        Returns:
            True if the VAD event is from the current turn, False otherwise
        """
        is_valid = self._vad_turn_id == self._current_turn_id
        if not is_valid and self._vad_turn_id >= 0:
            print(f"  ⚠️ [STT] Stale VAD event detected (vad_turn={self._vad_turn_id}, current={self._current_turn_id})")
        return is_valid
    
    def get_current_turn_id(self) -> int:
        """Get the current turn ID."""
        return self._current_turn_id
    
    async def ensure_healthy(self) -> bool:
        """Ensure the streaming STT is healthy, reconnect if needed."""
        if self.is_healthy():
            return True
        
        print("⚠️ [STT] Connection unhealthy, reconnecting...")
        await self._cleanup()
        if await self.connect():
            await self.start_listening(self._on_transcript, self._on_vad_event)
            return True
        return False
    
    async def disconnect(self) -> None:
        """Close the connection."""
        self._intentional_disconnect = True
        if getattr(self, '_reconnect_task', None) and not self._reconnect_task.done():
            import logging
            logger = logging.getLogger(__name__)
            logger.info("[VOICE_STT_RECONNECT_TASK_CANCEL]")
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
            self._reconnect_task = None
        await self._cleanup()
        print("🔌 Streaming STT disconnected")
    
    def get_stats(self) -> dict:
        """Get streaming statistics."""
        return {
            "chunks_sent": self.state.audio_chunks_sent,
            "total_bytes": self.state.total_audio_bytes,
            "audio_duration_s": self.state.total_audio_bytes / 2 / self.sample_rate,
            "speech_started": self.state.speech_started,
            "speech_ended": self.state.speech_ended,
            "transcript_length": len(self.state.final_transcript),
            "current_turn_id": self._current_turn_id,
            "transcript_turn_id": self._transcript_turn_id,
            "vad_turn_id": self._vad_turn_id,
        }


# =============================================================================
# BATCH STT (Fallback when streaming fails)
# =============================================================================

class SarvamRealtimeSTT:
    """
    Batch Speech-to-Text using Sarvam SDK.
    Used as fallback when TrueStreamingSTT fails.
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        language: str = "en-IN",
        model: str = "saarika:v2.5",
        sample_rate: int = 16000
    ):
        self.api_key = api_key or config.SARVAM_API_KEY
        self.language = language
        self.model = model
        self.sample_rate = sample_rate
        self.client: Optional[AsyncSarvamAI] = None
        self._ws_context = None
        self.ws = None
        self._start_time: Optional[float] = None
        
    async def connect(self, max_retries: int = 3, retry_delay: float = 1.0) -> bool:
        """Establish connection to Sarvam STT with retry logic."""
        import logging
        logger = logging.getLogger(__name__)
        for attempt in range(1, max_retries + 1):
            try:
                if attempt > 1:
                    logger.info(f"Batch STT connection retry {attempt}/{max_retries}...")
                else:
                    logger.info(f"Connecting to Sarvam Batch STT...")
                    
                self._start_time = time.perf_counter()
                
                self.client = AsyncSarvamAI(api_subscription_key=self.api_key)
                
                self._ws_context = self.client.speech_to_text_streaming.connect(
                    language_code=self.language,
                    model=self.model,
                    sample_rate=str(self.sample_rate),
                    high_vad_sensitivity="false",
                    vad_signals="true",
                    flush_signal="true"
                )
                
                self.ws = await asyncio.wait_for(
                    self._ws_context.__aenter__(),
                    timeout=5.0
                )
                
                connect_time = (time.perf_counter() - self._start_time) * 1000
                logger.info(f"[VOICE_STT_SOCKET] event=connected url='wss://api.sarvam.ai/speech-to-text-translate' model={self.model} language={self.language}")
                logger.info(f"Sarvam Batch STT connected in {connect_time:.0f}ms")
                return True
                
            except (asyncio.TimeoutError, TimeoutError):
                logger.warning(f"Batch STT connection timeout (attempt {attempt}/{max_retries})")
                await self._cleanup_connection()
                if attempt < max_retries:
                    await asyncio.sleep(retry_delay)
                    
            except asyncio.CancelledError:
                logger.warning(f"Batch STT connection cancelled (attempt {attempt}/{max_retries})")
                await self._cleanup_connection()
                if attempt < max_retries:
                    await asyncio.sleep(retry_delay)
                    
            except Exception as e:
                logger.error(f"Failed to connect to Sarvam Batch STT (attempt {attempt}/{max_retries}): {e}")
                await self._cleanup_connection()
                if attempt < max_retries:
                    await asyncio.sleep(retry_delay)
        
        logger.error(f"[VOICE_STT_SOCKET] event=closed close_reason='connection_failed' close_code=None")
        logger.error(f"Batch STT connection failed after {max_retries} attempts")
        return False
    
    async def _cleanup_connection(self) -> None:
        """Clean up failed connection attempt."""
        import logging
        logger = logging.getLogger(__name__)
        try:
            if self._ws_context:
                await self._ws_context.__aexit__(None, None, None)
                logger.info(f"[VOICE_STT_SOCKET] event=closed close_reason='cleanup' close_code=None")
        except Exception as e:
            logger.warning(f"[VOICE_STT_SOCKET] event=closed close_reason='cleanup_error' close_code=None error='{e}'")
        self.ws = None
        self._ws_context = None
        self.client = None
    
    def is_connected(self) -> bool:
        """Check if the WebSocket connection is active."""
        return self.ws is not None and self._ws_context is not None and not getattr(self.ws.client_connection, 'closed', True)
    
    async def ensure_connected(self) -> bool:
        """Ensure connection is alive, reconnect if needed."""
        if self.is_connected():
            return True
        return await self.connect(max_retries=2, retry_delay=0.3)
    
    async def reset_for_new_turn(self) -> None:
        """Reset state for a new turn without disconnecting."""
        self._start_time = time.perf_counter()

    async def send_audio(self, audio_data: bytes, encoding: str = "audio/wav") -> None:
        """Send audio to STT."""
        import logging
        logger = logging.getLogger(__name__)
        if not self.ws:
            logger.warning("Batch STT not connected")
            return
        
        try:
            audio_base64 = base64.b64encode(audio_data).decode('utf-8')
            logger.info(f"Sending {len(audio_data)} bytes of audio to Batch STT...")
            
            await self.ws.transcribe(
                audio=audio_base64,
                encoding=encoding,
                sample_rate=self.sample_rate
            )
            logger.info(f"[VOICE_STT_SOCKET] event=send_audio bytes={len(audio_data)}")
            logger.info(f"Audio sent to Batch STT")
            
        except Exception as e:
            logger.error(f"Error sending audio to Batch STT: {e}")
    
    async def flush(self) -> None:
        """Send flush signal."""
        import logging
        logger = logging.getLogger(__name__)
        if not self.ws:
            return
        
        try:
            await self.ws.flush()
            logger.info("[VOICE_STT_SOCKET] event=flush")
            logger.info("Batch STT flush signal sent")
        except Exception as e:
            logger.error(f"Error sending flush: {e}")
    
    async def receive(self, timeout_sec: float = 10.0) -> Optional[STTResult]:
        """Receive transcription result."""
        import logging
        logger = logging.getLogger(__name__)
        if not self.ws:
            return None
        
        try:
            logger.info("[VOICE_STT_RECEIVE_START] Waiting for Batch STT response...")
            
            async def _receive_loop():
                async for message in self.ws:
                    msg_type = getattr(message, 'type', None)
                    msg_data = getattr(message, 'data', None)
                    
                    elapsed = (time.perf_counter() - self._start_time) * 1000 if self._start_time else 0
                    logger.info(f"[VOICE_STT_SOCKET] event=receive message_type={msg_type} elapsed_ms={elapsed:.2f}")
                    
                    # Skip event messages (START_SPEECH, END_SPEECH)
                    if msg_type == 'events':
                        signal = getattr(msg_data, 'signal_type', None) if msg_data else None
                        if signal == 'END_SPEECH':
                            logger.info("End of speech detected, waiting for transcript...")
                        continue
                    
                    # Check for explicit error
                    if msg_type == 'error':
                        error_msg = getattr(msg_data, 'message', 'Unknown Error') if msg_data else 'Unknown Error'
                        logger.error(f"[VOICE_STT_SOCKET] event=error message='{error_msg}'")
                        raise RuntimeError(f"Sarvam STT returned error: {error_msg}")
                    
                    # This is the actual transcript data
                    if msg_type == 'data':
                        transcript = getattr(msg_data, 'transcript', '') if msg_data else ''
                        language = getattr(msg_data, 'language_code', self.language) if msg_data else self.language
                        
                        logger.info(f"[VOICE_STT_RECEIVE_FINAL] len={len(transcript)}")
                        logger.info(f"Batch Transcript: '{transcript}'")
                        logger.info(f"Language: {language}")
                        
                        latency = None
                        if self._start_time:
                            latency = (time.perf_counter() - self._start_time) * 1000
                        
                        return STTResult(
                            transcript=transcript,
                            is_final=True,
                            language_code=language,
                            latency_ms=latency
                        )
                    
                    # Handle dict responses (fallback)
                    if isinstance(message, dict):
                        m_type = message.get('type')
                        logger.info(f"[VOICE_STT_SOCKET] event=receive message_type={m_type} elapsed_ms={elapsed:.2f}")
                        
                        if m_type == 'error':
                            error_msg = message.get('data', {}).get('message', 'Unknown Error')
                            logger.error(f"[VOICE_STT_SOCKET] event=error message='{error_msg}'")
                            raise RuntimeError(f"Sarvam STT returned error: {error_msg}")
                            
                        if m_type == 'data' or 'transcript' in message:
                            transcript = message.get('transcript', '')
                            logger.info(f"[VOICE_STT_RECEIVE_FINAL] len={len(transcript)}")
                            return STTResult(
                                transcript=transcript,
                                is_final=True,
                                language_code=message.get('language_code', self.language),
                                latency_ms=None
                            )
                return None
                
            return await asyncio.wait_for(_receive_loop(), timeout=timeout_sec)
            
        except asyncio.TimeoutError:
            logger.warning("[VOICE_STT_RECEIVE_TIMEOUT] Batch STT timeout")
            raise TimeoutError("Batch STT timeout")
        except Exception as e:
            logger.error(f"[VOICE_STT_RECEIVE_ERROR] Error receiving Batch STT: {e}")
            raise Exception(f"Batch STT Error: {e}")
    
    async def disconnect(self) -> None:
        """Close connection."""
        if self._ws_context:
            try:
                await self._ws_context.__aexit__(None, None, None)
                print("🔌 Sarvam Batch STT disconnected")
            except:
                pass
        self.ws = None
        self._ws_context = None
        self.client = None


# =============================================================================
# STREAMING AUDIO PIPELINE
# =============================================================================

class StreamingAudioPipeline:
    """
    Complete streaming pipeline that integrates:
    - Twilio audio → STT streaming
    - VAD-based end-of-speech detection  
    - Parallel LLM processing
    
    This is the main class to use for ultra-low latency voice processing.
    """
    
    def __init__(
        self,
        language: str = "unknown",
        sample_rate: int = 16000,
        on_transcript_ready: Optional[Callable] = None,
        on_speech_end: Optional[Callable] = None
    ):
        self.language = language
        self.sample_rate = sample_rate
        self.on_transcript_ready = on_transcript_ready
        self.on_speech_end = on_speech_end
        
        self.stt: Optional[TrueStreamingSTT] = None
        self._is_active = False
        self._accumulated_pcm = b""  # Fallback buffer
        
    async def start(self) -> bool:
        """Initialize and start the streaming pipeline."""
        self.stt = TrueStreamingSTT(
            language=self.language,
            sample_rate=self.sample_rate
        )
        
        if not await self.stt.connect():
            return False
        
        # Start background listener with VAD callback
        await self.stt.start_listening(
            on_transcript=self._handle_transcript,
            on_vad_event=self._handle_vad
        )
        
        self._is_active = True
        return True
    
    async def _handle_transcript(self, transcript: str, is_final: bool):
        """Handle transcript updates."""
        if self.on_transcript_ready and is_final:
            await self._safe_callback(self.on_transcript_ready, transcript)
    
    async def _handle_vad(self, event_type: str, turn_id: int):
        """Handle VAD events with turn validation."""
        # Validate event is from current turn
        if self.stt and turn_id != self.stt.get_current_turn_id():
            print(f"  ⚠️ [Pipeline] Ignoring stale VAD {event_type} (turn={turn_id}, current={self.stt.get_current_turn_id()})")
            return
        
        if event_type == "END_SPEECH" and self.on_speech_end:
            await self._safe_callback(self.on_speech_end)
    
    async def _safe_callback(self, callback, *args):
        """Safely execute callback."""
        try:
            result = callback(*args)
            if asyncio.iscoroutine(result):
                await result
        except Exception as e:
            print(f"⚠️ Pipeline callback error: {e}")
    
    async def process_audio_chunk(self, pcm_chunk: bytes) -> None:
        """
        Process an audio chunk from Twilio.
        Streams directly to STT for real-time transcription.
        """
        if not self._is_active or not self.stt:
            return
        
        # Stream to STT immediately
        await self.stt.stream_chunk(pcm_chunk)
        
        # Also accumulate for fallback
        self._accumulated_pcm += pcm_chunk
    
    async def force_finalize(self) -> StreamingSTTResult:
        """
        Force finalization of current audio.
        Use this when silence is detected by local VAD.
        """
        if self.stt:
            await self.stt.flush()
            return await self.stt.get_final_transcript(timeout=3.0)
        return StreamingSTTResult(transcript="", is_final=True)
    
    async def get_transcript(self, timeout: float = 5.0) -> StreamingSTTResult:
        """Get the current/final transcript."""
        if self.stt:
            return await self.stt.get_final_transcript(timeout)
        return StreamingSTTResult(transcript="", is_final=True)
    
    async def reset_for_new_turn(self):
        """Reset for a new conversation turn."""
        self._accumulated_pcm = b""
        if self.stt:
            await self.stt.reset_for_new_turn()
    
    async def stop(self):
        """Stop the pipeline."""
        self._is_active = False
        if self.stt:
            await self.stt.disconnect()
            self.stt = None
    
    def get_stats(self) -> dict:
        """Get pipeline statistics."""
        if self.stt:
            return self.stt.get_stats()
        return {}


# Utility function for quick testing
async def test_streaming_stt(audio_chunks: list, language: str = "en-IN"):
    """
    Test streaming STT with a list of audio chunks.
    
    Args:
        audio_chunks: List of PCM audio chunks
        language: Language code
    """
    stt = TrueStreamingSTT(language=language)
    
    if not await stt.connect():
        print("Failed to connect")
        return
    
    try:
        # Start listener
        await stt.start_listening()
        
        # Stream all chunks
        for i, chunk in enumerate(audio_chunks):
            await stt.stream_chunk(chunk)
            await asyncio.sleep(0.02)  # Simulate real-time (20ms chunks)
        
        # Flush and get result
        await stt.flush()
        result = await stt.get_final_transcript()
        
        print(f"\n📊 Streaming STT Results:")
        print(f"   Transcript: {result.transcript}")
        print(f"   Language: {result.language_code}")
        print(f"   Latency: {result.latency_ms:.0f}ms" if result.latency_ms else "   Latency: N/A")
        print(f"   Stats: {stt.get_stats()}")
        
    finally:
        await stt.disconnect()
