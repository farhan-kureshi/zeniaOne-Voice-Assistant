import audioop
import io
import wave
import base64
import logging

logger = logging.getLogger(__name__)

def sarvam_to_twilio(chunk_bytes: bytes, input_rate: int = 24000) -> bytes:
    """
    Dummy for twilio compatibility.
    """
    return chunk_bytes

def convert_to_exotel_pcm(wav_bytes: bytes) -> bytes:
    """
    Reads a WAV file (from bytes) and returns 16-bit, 8000Hz, Mono PCM (raw bytes)
    which Exotel requires.
    """
    try:
        with io.BytesIO(wav_bytes) as wav_io:
            with wave.open(wav_io, 'rb') as w:
                nchannels = w.getnchannels()
                sampwidth = w.getsampwidth()
                framerate = w.getframerate()
                
                pcm_data = w.readframes(w.getnframes())
                
                # Convert to mono if stereo
                if nchannels == 2:
                    pcm_data = audioop.tomono(pcm_data, sampwidth, 1, 1)
                
                # Resample to 8000Hz if needed
                if framerate != 8000:
                    pcm_data, _ = audioop.ratecv(pcm_data, sampwidth, 1, framerate, 8000, None)
                    
                # Exotel needs 16-bit. If it's 8-bit, convert to 16-bit
                if sampwidth == 1:
                    pcm_data = audioop.lin2lin(pcm_data, 1, 2)
                    
                return pcm_data
    except Exception as e:
        logger.error(f"Error converting audio to Exotel format: {e}")
        return b""
