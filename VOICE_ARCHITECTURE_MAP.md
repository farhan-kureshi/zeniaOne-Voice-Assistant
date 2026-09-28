# VOICE ARCHITECTURE MAP

**VOICE BUTTON** (zenaipex-frontend/components/ai-bot/floating-ai-bot.tsx)
↓ triggers setVoiceModeEnabled(true)
**MOUNT** (zenaipex-frontend/components/ai-bot/voice-mode-overlay.tsx)
↓ triggers useEffect -> initVoiceSession()
**conversation** (zenaipex-frontend/components/ai-bot/voice-mode-overlay.tsx via gentsApi.createConversation)
↓ parallel execution fork
├── **welcome TTS** (gentsApi.speak -> zenaipex/api/v1/agents.py)
│   ↓ returns Base64 audio
├── **browser playback** (udio.play() in playWelcomeGreeting)
│
└── **microphone** (
avigator.mediaDevices.getUserMedia in startListening)
    ↓ triggers VAD and AudioContext
    **AudioContext** (udioContextRef.current)
    ↓ onaudioprocess calibration phase finishes (400ms)
    **WebSocket** (ws = new WebSocket(wsUrl))
    ↓ connects to zenaipex/api/v1/agents.py /voice-stream
    **STT** (modules/sarvam_stt.py via WebSocket forwarding)
    ↓ user speaks ("Speaking" state triggered by ms > onsetThreshold)
    **transcript** (Backend receives STT final text)
    ↓
    **AI** (zenaipex/ai/llm.py)
    ↓
    **RAG** (zenaipex/ai/rag.py / zenaipex/ai/vector_store.py)
    ↓
    **response** (LLM generates chunks)
    ↓
    **TTS** (modules/sarvam_tts.py)
    ↓
    **audio transport** (Backend streams i_audio_pcm via WebSocket)
    ↓
    **browser playback** (ws.onmessage enqueues chunks in oice-mode-overlay.tsx)
    ↓
    **Listening** (VAD resumes, UI resets)
