# VOICE ROOT CAUSE CANDIDATES

### LIKELY: Missing getUserMedia User Gesture Context
- **Issue**: By executing startListening() asynchronously within a useEffect after wait agentsApi.createConversation, the strict user-gesture context of the initial button click is lost. Browsers like Safari automatically block getUserMedia or udio.play() outside of a synchronous user gesture.
- **Exact File**: zenaipex-frontend/components/ai-bot/voice-mode-overlay.tsx
- **Exact Function**: startListening, playWelcomeGreeting
- **Evidence**: The backend processes /speak correctly (200 OK), but the frontend completely halts. No microphone prompts, no WebSockets opened. 
- **First Commit**: Introduced during the concurrent architectural refactor.
- **Existed in last known working version?**: No. The last known version relied on immediate synchronous initialization.
- **Confidence**: HIGH

### CONFIRMED: Premature Listening State (Race Condition)
- **Issue**: ws.onopen triggers setVoiceState("listening") because it incorrectly assumes that if udioPlayerRef.current.paused is true, the welcome audio has already finished. In reality, the /speak API is still fetching, and the audio hasn't even *started* playing.
- **Exact File**: zenaipex-frontend/components/ai-bot/voice-mode-overlay.tsx
- **Exact Function**: ws.onopen inline handler.
- **Evidence**: startListening() runs ws.onopen within 50ms, while /speak takes 500ms+. The UI switches to "Listening" and activates the VAD microphone *before* the welcome TTS actually plays through the speakers.
- **First Commit**: Introduced during the concurrent architectural refactor.
- **Existed in last known working version?**: No.
- **Confidence**: HIGH

### POSSIBLE: No physical microphone device attached
- **Issue**: If the testing environment lacks a microphone, getUserMedia throws NotFoundError, caught by the .catch block, which sets oiceActiveRef.current = false.
- **Exact File**: zenaipex-frontend/components/ai-bot/voice-mode-overlay.tsx
- **Exact Function**: startListening
- **Evidence**: When oiceActiveRef becomes false, playWelcomeGreeting intentionally aborts after the /speak fetch, completely halting the frontend UI without throwing a fatal crash.
- **Existed in last known working version?**: Yes.
- **Confidence**: MEDIUM
