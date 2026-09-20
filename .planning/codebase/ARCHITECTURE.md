# Architecture

## Data Flow
```mermaid
graph TD
    A[Caller] -->|Audio| B(Twilio)
    B -->|WebSocket| C[FastAPI realtime_app.py]
    C -->|mu-law to PCM| D[Sarvam saarika:v2.5 STT]
    D -->|Text| E[Pinecone RAG Vector Search]
    E -->|Context + Query| F[Sarvam sarvam-105b LLM]
    F -->|Text Response| G[Sarvam bulbul:v3 TTS]
    G -->|PCM to mu-law| C
    C -->|WebSocket| B
    B -->|Audio| A
```

## Key Components
1. **Twilio Media Streams**: Handles the telephony side, routing phone calls to our WebSocket server.
2. **FastAPI Application**: The core orchestrator. Manages WebSocket connections and parallel processing tasks.
3. **Audio Utils**: Converts Twilio's mu-law audio to standard PCM format for Sarvam using FFmpeg.
4. **Pinecone**: Acts as the memory bank, providing relevant hospital documentation for RAG.
5. **MongoDB/Google Sheets**: Stores generated actions such as appointment bookings.
