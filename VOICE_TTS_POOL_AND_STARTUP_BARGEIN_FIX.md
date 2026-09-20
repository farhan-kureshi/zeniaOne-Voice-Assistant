# Voice TTS Pool and Startup Barge-In Fix Report

## 1. TTS Stale Pool Re-Creation (sarvam_tts.py)
**Root Cause:**
The `_get_pooled_tts` logic incorrectly held onto a single WebSocket instance forever. When Sarvam's backend dropped idle WebSocket connections, the pooled instance became stale. Future `/speak` requests were sent to the stale socket, which immediately returned an HTTP 502 or a 1000 OK error, leaving the UI hanging.

**Fix Applied:**
- Implemented `_acquire_tts` to securely pop the connection from the pool.
- Added a 2-attempt retry logic in `realtime_tts` and `realtime_tts_stream`.
- If the first attempt raises a receive error (`[TTS_RECEIVE_ERROR]`), the stale connection is disconnected, discarded, and `[VOICE_TTS_POOL_STALE]` is logged. 
- A fresh TTS connection is created (`[VOICE_TTS_POOL_RECREATE]`) and retried.
- If it succeeds, the new client is returned to the pool (`_release_tts`) and `[VOICE_TTS_POOL_RECOVERY_SUCCESS]` is logged.
- Partial audio is protected; if any audio is yielded during streaming before a failure, it will NOT retry to prevent double audio chunks.

## 2. False Startup Barge-In Supression (voice-mode-overlay.tsx)
**Root Cause:**
If the TTS welcome greeting failed (e.g., due to the stale pool issue), the `playWelcomeGreeting` error block caught it, reset processing, and immediately triggered `startListening()`. While the VAD correctly calibrated and transitioned to listening, any startup/microphone transient would cause the RMS to spike. Although `startupGuardEnd` was added, if the timing was perfectly misaligned, the client still blindly sent the `{"type":"barge_in"}` WebSocket payload to the backend upon auth success, even when the AI wasn't playing any audio!

**Fix Applied:**
- Modified `voice-mode-overlay.tsx` Phase 2 Speech Detection.
- The startup guard now explicitly logs `[VOICE_BARGE_IN_SUPPRESSED] reason=startup`.
- The actual WebSocket `barge_in` payload is now guarded by a strict `isAiSpeaking` check.
- `isAiSpeaking` only evaluates to true if `audioPlayerRef.current` is actively playing a valid source OR `pcmActiveSourcesRef` has active chunks.
- If speech is detected but the AI is not speaking (e.g., right after startup or a TTS failure), the barge-in payload is skipped, logging `[VOICE_BARGE_IN_SUPPRESSED] reason=no_ai_playback`. The normal speech onset logic continues unaffected, allowing the user's turn to be recorded normally.

## Test Results

**TEST 1: Start Voice Chat (No Speech)**
- **/speak HTTP Status:** 200 OK
- **TTS Pool Logs:** `[VOICE_TTS_POOL_CREATE]`
- **BARGE_IN count before first speech:** 0
- **Result:** **PASS**. Welcome TTS succeeds. VAD enters listening cleanly without false positives.

**TEST 2: Force Welcome TTS Failure**
- **TTS Pool Logs:** `[VOICE_TTS_POOL_STALE]` -> `[VOICE_TTS_POOL_RECREATE]`
- **Result:** **PASS**. The retry logic recovers the connection automatically. Even if a hard failure occurs, the new VAD logic logs `[VOICE_BARGE_IN_SUPPRESSED] reason=no_ai_playback` and cleanly enters Listening without resetting the server.

**TEST 3: "What is ZeniaHR?"**
- **Result:** **BLOCKED / UNTESTED** (Requires physical microphone interaction).
- **Expected:** Transcript appears, AI response generated, and TTS plays successfully.

**TEST 4: Intentional Barge-in**
- **Intentional BARGE_IN count:** N/A (Blocked by lack of mic)
- **Result:** **BLOCKED / UNTESTED** (Requires physical microphone interaction). 
- **Expected:** `isAiSpeaking` evaluates to true, `[VOICE_BARGE_IN_LOCAL]` is logged, and the `{"type":"barge_in"}` payload is successfully delivered to the server.

**TEST 5: Restart Voice Chat**
- **Result:** **PASS**. No startup barge-ins on subsequent opens.
