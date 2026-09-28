# ZeniaOne Voice Assistant

A real-time multilingual voice agent SaaS platform. Handles customer queries and booking over phone calls using Exotel, Sarvam AI, and Pinecone.

## Architecture

Exotel (caller) -> Sarvam STT (saarika:v2.5) -> Pinecone RAG -> Sarvam-105B -> Sarvam TTS (bulbul:v3) -> Exotel (caller)

- **STT**: Sarvam saarika:v2.5 - real-time streaming speech-to-text
- **RAG**: Pinecone vector search with sentence-transformers/all-MiniLM-L6-v2 embeddings
- **LLM**: Sarvam sarvam-105b - multilingual reasoning
- **TTS**: Sarvam bulbul:v3 - streaming text-to-speech
- **Telephony**: Exotel Media Streams (WebSocket)

## Folder Structure

.
├── zenaipex/             # FastAPI backend (Exotel webhook + voice pipeline)
├── zenaipex-frontend/    # Next.js / React frontend dashboard
├── .env                  # Environment Variables
└── README.md

## Running the Project

### 1. Start the Backend
python -m uvicorn zenaipex.main:app --host 0.0.0.0 --port 8002 --reload

### 2. Start the Frontend
cd zenaipex-frontend
npm run dev

### 3. Setup Exotel Webhook
Run ngrok or cloudflared to expose port 8002:
ngrok http 8002

In your Exotel Voicebot applet, paste the WebSocket URL:
wss://<your-ngrok-domain>/api/v1/webhook/exotel/advanced/<company_id>/<agent_id>/media-stream
