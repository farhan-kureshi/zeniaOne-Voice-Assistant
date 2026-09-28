# VOICE MODE STARTUP: ROOT CAUSE REPORT

## 1. Exact Startup Sequence (Expected)
1. `VoiceModeDock` mounts. Initial state is `"connecting"`.
2. `useEffect` runs `initVoiceSession()`.
3. Calls `agentsApi.createConversation()` (if `activeConvId` is `tmp`).
4. Calls `playWelcomeGreeting()`.
5. Updates state to `"speaking"`.
6. Fetches TTS via `agentsApi.speak()`.
7. Plays audio via browser `audio.play()`.
8. On playback completion (`audio.onended`), calls `startListening()`.
9. `startListening()` acquires the microphone (`getUserMedia`).
10. `startStreamingRecorder()` opens the STT WebSocket (`/voice-stream`).
11. State changes to `"listening"`.

## 2. Last Confirmed Working Step
- **Conversation Creation:** Succeeded.
- **TTS Fetch:** Succeeded (Backend generated audio and returned HTTP 200 OK for `/speak`).

## 3. First Missing Step
- **Browser Audio Playback:** The frontend never actually calls `audio.play()`.
- Consequently, `audio.onended` never fires, the microphone is never acquired, the WebSocket is never opened, and the UI never progresses past `"connecting"`.

## 4. Exact Function Responsible
- `playWelcomeGreeting()` in `voice-mode-overlay.tsx`
- The `useEffect` mount/unmount cleanup cycle in `VoiceModeDock`.

## 5. Exact Condition Causing the Stop
The sequence is aborted mid-flight by this specific early-return guard inside `playWelcomeGreeting()`:
```typescript
if (!voiceActiveRef.current || playbackGenerationRef.current !== currentPlaybackId) {
   console.log("[VOICE_WELCOME_REQUEST] Aborted due to inactive voice or generation mismatch");
   return;
}
```

## 6. Detailed Root Cause Analysis (React 18 Strict Mode Async Race Condition)
The issue is caused by how React 18 Strict Mode mounts, unmounts, and remounts components in development to simulate concurrent features:

1. **Fiber 1 Mounts:** `VoiceModeDock` renders. Initial state is `"connecting"`.
2. **Fiber 1 Effect:** `welcomePlayedRef.current` is set to `true`. `initVoiceSession` begins running asynchronously (awaits `createConversation`).
3. **Fiber 1 Unmounts:** Strict Mode immediately unmounts Fiber 1. The cleanup function runs: `releaseAll()` executes, setting `voiceActiveRef.current = false`.
4. **Fiber 2 Mounts:** Strict Mode remounts the component (this is the one visible on screen). State is initialized to `"connecting"`.
5. **Fiber 2 Effect:** Because `useRef` values persist across Strict Mode remounts, `welcomePlayedRef.current` is *still* `true`. 
6. **Fiber 2 Blocked:** Fiber 2 hits the guard `if (!welcomePlayedRef.current)` and completely skips initialization. Its UI remains permanently stuck at `"connecting"`.
7. **Fiber 1 Resumes:** Meanwhile, the async closure from Fiber 1 finishes `createConversation` and calls `playWelcomeGreeting()`. 
8. **Fiber 1 Calls Backend:** Fiber 1 successfully awaits `agentsApi.speak()`. The backend logs the successful TTS generation.
9. **Fiber 1 Aborts:** Once the `speak()` network call resolves, Fiber 1 reaches the guard `if (!voiceActiveRef.current) return;`. Because Fiber 1's cleanup function previously set `voiceActiveRef.current = false` (in Step 3), the function silently aborts. 

Because Fiber 1 aborted before calling `audio.play()`, and Fiber 2 was blocked from ever starting, the WebSocket is never reached and the UI is stuck.

## 7. Answers to Critical Checks
- **Does frontend wait for TTS audio playback to END before opening WebSocket?** Yes. It waits for `audio.onended`.
- **Is an audio onended/onfinish callback required?** Yes. The sequence relies on `onended` to trigger `startListening()`.
- **Can that callback fail to fire?** Yes, if `audio.play()` is never called, or if the browser blocks autoplay (though errors are caught).
- **Does the frontend call getUserMedia after /speak succeeds?** Yes, but only after audio playback ends.
- **Does it call WebSocket after /speak succeeds?** Yes, after the microphone is acquired.
- **Is NEXT_PUBLIC_STREAMING_VOICE preventing the WebSocket path?** No, the code execution never reaches that check.
- **Is a voice session ref cleanup function cancelling the startup sequence?** **YES.** `releaseAll()` sets `voiceActiveRef.current = false`, which causes the async TTS fetch to abort upon completion.
- **Is the overlay being remounted/unmounted after conversation creation?** **YES.** React 18 Strict Mode unmounts and remounts it synchronously on the first render.

## 8. Root Cause Confidence
**High.** The sequence of events perfectly explains why the backend sees the TTS generation but the frontend UI never updates and the WebSocket never opens.

## 9. Smallest Proposed Fix (Do Not Implement)
Remove the `if (!welcomePlayedRef.current)` guard entirely. Rely on the `useEffect` cleanup function to abort any stale network calls, and allow the active component mount to run its initialization sequence normally. Alternatively, reset `welcomePlayedRef.current = false` inside the `releaseAll()` cleanup function so that a remounted component knows it is allowed to initialize.
