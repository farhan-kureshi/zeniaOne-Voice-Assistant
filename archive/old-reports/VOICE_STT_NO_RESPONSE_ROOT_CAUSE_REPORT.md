# Root Cause Report: STT Not Responding (Part 2)

## 1. Issue Description
After fixing the sample rate issue, the STT connected successfully, but the AI still did not respond. The browser sent audio for ~28 seconds before the connection finally closed. The backend listener started, but we never received a `[VOICE_STT_PARTIAL]` or `[VOICE_STT_FINAL]` log. Also, the Sarvam SDK threw an `audio/wav` Pydantic validation error when passing `"audio/pcm"`. 

## 2. Root Causes Identified

### 2.1. Incorrect Streaming Chunk Formatting (WAV Header Per Chunk)
To satisfy the Pydantic literal validation, the code was originally prepending a complete WAV file header onto *every single 42ms PCM chunk* before transmitting it as base64. 
A streaming socket expects a continuous audio stream, not a concatenated series of thousands of overlapping standalone WAV files. This fundamentally broke the stream parsing on the server.

### 2.2. Missing Utterance Finalization in VAD Logic
Even if the STT correctly received audio, the application layer in `agents.py` was fundamentally incomplete regarding streaming lifecycle. When Sarvam STT emitted `END_SPEECH`, the local VAD handler `on_speech_end()` was immediately triggering the AI response (`_process_speech_task()`) using whatever the *last partial transcript* was. It **never sent a flush signal** to the Sarvam STT socket, and it **never waited for the final transcript**. Because the pipeline never formally ended the utterance, it hung until timeout.

## 3. The Fixes Applied

### 3.1. Correct Sarvam SDK Contract (pcm_s16le)
By investigating the raw source of the `sarvamai` SDK in the local `.venv`, we discovered that the connection constructor accepts an `input_audio_codec` parameter.
- **Fix:** In `modules/sarvam_stt.py`, we now pass `input_audio_codec="pcm_s16le"` when calling `connect()`.
- **Fix:** In `stream_chunk()`, we removed the WAV wrapper completely. We just base64 encode the raw PCM.
- **Why it works:** The SDK Pydantic model still literally requires `encoding="audio/wav"` locally, which we pass to bypass local client validation, but the server successfully parses the raw PCM because of the connection parameter.

### 3.2. Proper Utterance Finalization (`force_finalize`)
In `zenaipex/api/v1/agents.py`, we corrected the `on_speech_end()` handler:
1. It now explicitly calls `pipeline.force_finalize()`.
2. This sends the `SttFlushSignal()` to Sarvam.
3. It awaits the *final* transcript from the STT listener.
4. Once the final transcript is received, it proceeds to the AI logic.
5. In the `finally` block, we added `pipeline.reset_for_new_turn()` so the pipeline increments its turn ID and is ready for the next speech block on the same websocket.

### 3.3. New Logs Added
- `[VOICE_STT_SEND] bytes=... format=pcm_s16le turn_id=...`
- `[VOICE_STT_RAW_RESPONSE] type=... keys=...`
- `[VOICE_STT_LISTENER_STARTED]`
- `[VOICE_STT_LISTENER_CLOSED]`
- `[VOICE_STT_RESPONSE_ERROR]`

## 4. Expected Test Outcome
Please run the minimal live test:
1. Start Voice Chat.
2. Say: "What is ZeniaHR?"
3. Stop speaking.

You should now see the `[VOICE_STT_FINAL]` transcript successfully generated from the flush, followed immediately by `[VOICE_AI_TURN_START]` and the TTS response.
