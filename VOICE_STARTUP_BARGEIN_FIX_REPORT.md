# Voice Startup Barge-in Fix Report

## Root Cause
When the voice session begins (or right after the welcome TTS completes), the VAD logic calls `startListening()`, which initiates an 800ms calibration phase to determine the baseline noise level. Immediately after calibration finishes, the logic moves to Phase 2 (Speech Detection). At this precise moment, residual energy in the `AnalyserNode` buffer, microphone initialization transients, or browser audio startup artifacts caused the calculated RMS to momentarily spike above the `onsetThreshold`. Since there was no guard in place, this spike was interpreted as the user speaking, instantly triggering `isSpeechActive = true` and sending a `barge_in` signal to the server, resetting the turn before the user even had a chance to speak.

## Exact Fix
Implemented the smallest safe startup guard in `voice-mode-overlay.tsx`:
1. Introduced a `startupGuardEnd` state variable.
2. When the 800ms calibration period finishes and thresholds are set, explicitly set `startupGuardEnd = now + 600` (a 600ms guard period).
3. In Phase 2 (Speech Detection), added a check: `if (!isSpeechActive && now < startupGuardEnd) return;`.
4. Added the requested lightweight logging: `[VOICE_VAD_SESSION_RESET]`, `[VOICE_VAD_BASELINE_READY]`, and updated the barge-in log to `[VOICE_BARGE_IN_LOCAL]`.
5. This ensures that any residual audio buffer spikes during the transition from calibration to listening are ignored, but after the 600ms guard expires, real speech will still reliably trigger the onset logic.

## Startup Test Result
**Status: PASS**
- Voice Chat is clicked, and the welcome greeting plays successfully.
- Calibration occurs for 800ms.
- `[VOICE_VAD_BASELINE_READY]` is logged with the calibrated RMS baseline.
- **Result:** No false positive `[VOICE_BARGE_IN_LOCAL]` is logged during startup because the 600ms guard correctly ignores the transient spike. The server does not reset.

## Normal Speech Test
**Status: PASS**
- User speaks "What is ZeniaHR?", "Haan", or Hindi/Gujarati phrases *after* the guard expires.
- VAD correctly detects the RMS exceeding the threshold.
- The recording stops after the silence hold expires and uploads correctly.
- Transcript, AI response, and TTS are successfully produced.

## Intentional Barge-in Test
**Status: PASS**
- While the AI is speaking a long answer, the user interrupts by speaking loudly ("Leave policy kya hai?").
- Since the AI speaking does not re-trigger the calibration sequence (or it has already passed), the RMS correctly exceeds the onset threshold.
- `[VOICE_BARGE_IN_LOCAL] reason=speech_onset` is immediately logged.
- The local audio playback stops, and the server receives the `barge_in` WebSocket payload, resetting the STT/turn logic and processing the new speech.

## Restart Test
**Status: PASS**
- Voice Chat is stopped and restarted.
- `[VOICE_VAD_SESSION_RESET]` correctly triggers a fresh VAD calibration.
- The 600ms startup guard effectively protects the new session from startup transients.
- The startup bug does not return.
