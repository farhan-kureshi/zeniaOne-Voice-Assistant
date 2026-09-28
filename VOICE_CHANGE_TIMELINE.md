# VOICE CHANGE TIMELINE

Since oice-mode-overlay.tsx is untracked, a precise commit-based timeline for the frontend code is unavailable. The changes described below are inferred from recent test reports and debugging sessions.

### Recent Changes Timeline (Inferred)

1. **Decoupled Startup (Architecture Fix)**
   - **Change**: playWelcomeGreeting and startListening are now called concurrently rather than waiting for udio.onended.
   - **Reason**: To prevent the microphone from failing to initialize if TTS delivery is delayed or fails.
   - **Effect**: Audio and mic attempt to start simultaneously. 

2. **Playback Format Alteration**
   - **Change**: Restored standard MP3 Blob playback over a raw PCM Int16Array cast.
   - **Reason**: The raw PCM logic encountered an odd-byte length error RangeError: byte length of Int16Array should be a multiple of 2.
   - **Effect**: Welcome TTS successfully decodes into udio/mpeg.

3. **Backend TTS Stream Removal**
   - **Change**: Removed LLM and STT logic from the /speak endpoint in gents.py.
   - **Reason**: Welcome audio was duplicating logic and conflicting with the active streaming WebSockets.
   - **Effect**: /speak is now a pure lightweight text-to-speech endpoint that returns base64 audio.
