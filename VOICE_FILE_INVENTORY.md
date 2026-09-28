# VOICE FILE INVENTORY

## Active Voice/Audio Modules

### zenaipex-frontend/components/ai-bot/voice-mode-overlay.tsx
- **Existence**: Active (Untracked in git, currently local only)
- **Main Responsibility**: Manages the entire Voice Mode UI, AudioContext, VAD, STT WebSocket streaming, and TTS playback.
- **Imports**: React hooks, gentsApi, lib/utils
- **Important Functions**: initVoiceSession, startListening, playWelcomeGreeting, suspendMic, eleaseAll, stopAndSubmit
- **Usage**: Used by loating-ai-bot.tsx, expanded-ai-bot.tsx, hero-ai-bot.tsx

### zenaipex/api/v1/agents.py
- **Existence**: Active
- **Main Responsibility**: Exposes REST/WebSocket endpoints for agent interaction (/speak, /voice-stream).
- **Imports**: modules.sarvam_tts, modules.sarvam_stt, zenaipex.ai.llm
- **Important Functions**: gent_speak, gent_voice_stream
- **Usage**: Called by frontend oice-mode-overlay.tsx.

### modules/sarvam_tts.py
- **Existence**: Active
- **Main Responsibility**: Handles WebSocket connection to Sarvam TTS API.
- **Important Functions**: ealtime_tts

### modules/sarvam_stt.py
- **Existence**: Active
- **Main Responsibility**: Handles WebSocket streaming of PCM audio for Speech-to-Text via Sarvam API.
- **Important Functions**: sarvam_stt_stream

### modules/audio_utils.py
- **Existence**: Active
- **Main Responsibility**: Audio conversion utilities (e.g. PCM manipulation, sample rate conversion).

### zenaipex-frontend/lib/data/voices.ts
- **Existence**: Active
- **Main Responsibility**: Stores available TTS voice identifiers for the application.

## Test / Diagnostic Files
- zenaipex/enable_sarvam.py: Script to enable/test Sarvam integrations.
- rchive/old-reports/*: Historical root-cause reports from previous AI debugging sessions.
