# RK Hospital Voice Agent

A real-time multilingual voice agent for RK Hospital. Handles patient queries and appointment booking over phone calls using Twilio, Sarvam AI, and Pinecone.

## Architecture

```
Twilio (caller) → Sarvam STT (saarika:v2.5) → Pinecone RAG → Sarvam-105B → Sarvam TTS (bulbul:v3) → Twilio (caller)
```

- **STT**: Sarvam `saarika:v2.5` — real-time streaming speech-to-text
- **RAG**: Pinecone vector search with `sentence-transformers/all-MiniLM-L6-v2` embeddings
- **LLM**: Sarvam `sarvam-105b` — multilingual reasoning (English, Hindi, Gujarati, Hinglish)
- **TTS**: Sarvam `bulbul:v3` — streaming text-to-speech
- **Telephony**: Twilio Media Streams (WebSocket)
- **Terminal Chatbot**: `chat.py` — RAG chatbot without voice, for testing

## Folder Structure

```
.
├── realtime_app.py       # FastAPI production server (Twilio + full voice pipeline)
├── config.py             # All configuration (loaded from .env)
├── chat.py               # Terminal RAG chatbot for testing
├── seed_knowledge.py     # Script to load hospital docs into Pinecone
├── pyproject.toml        # Project dependencies
├── requirements.txt      # Pip-compatible dependencies
├── .env                  # Secrets (NOT committed)
├── .env.example          # Template for .env
├── modules/
│   ├── llm_client.py     # Sarvam-105B LLM interface + RAG helpers
│   ├── vector_store.py   # Pinecone singleton + similarity search
│   ├── sarvam_stt.py     # Sarvam STT (streaming WebSocket)
│   ├── sarvam_tts.py     # Sarvam TTS (streaming WebSocket, bulbul:v3)
│   ├── audio_utils.py    # mu-law ↔ PCM ↔ WAV conversion (requires FFmpeg)
│   ├── mongodb.py        # Appointment and scheduled call storage
│   └── google_sheets.py  # Appointment export to Google Sheets
├── knowledge_docs/       # Plain-text hospital knowledge files (seeded into Pinecone)
├── call_trigger/         # Static web UI and scripts for outbound calls
└── tests/                # Integration and smoke tests (do NOT run paid-API tests in CI)
```

## Environment Variables

Copy `.env.example` to `.env` and fill in all values:

```bash
cp .env.example .env
```

| Variable | Description | Required |
|---|---|---|
| `SARVAM_API_KEY` | Sarvam AI API key | ✅ |
| `PINECONE_API_KEY` | Pinecone API key | ✅ |
| `PINECONE_INDEX_NAME` | Pinecone index name (e.g. `hospital-knowledge`) | ✅ |
| `TWILIO_ACCOUNT_SID` | Twilio Account SID | ✅ (voice calls) |
| `TWILIO_AUTH_TOKEN` | Twilio Auth Token | ✅ (voice calls) |
| `TWILIO_PHONE_NUMBER` | Twilio phone number | ✅ (voice calls) |
| `NGROK_URL` | Your public ngrok URL (for Twilio webhook) | ✅ (voice calls) |
| `MONGODB_URI` | MongoDB connection string | Optional |
| `GOOGLE_SHEET_ID` | Google Sheets ID for appointment export | Optional |

## Setup

### 1. Install dependencies

```bash
# Using uv (recommended)
uv sync

# Or pip
pip install -r requirements.txt
```

### 2. Install FFmpeg

FFmpeg is required for audio conversion (mu-law ↔ PCM).

```bash
# Windows (winget)
winget install ffmpeg
```

### 3. Seed the knowledge base

This loads the `.txt` files in `knowledge_docs/` into Pinecone. Run **once** after setup or when knowledge changes.

```bash
python seed_knowledge.py
```

> ⚠️ Requires `PINECONE_API_KEY` and `PINECONE_INDEX_NAME` in `.env`.

## Running

### Terminal RAG Chatbot (no voice, minimal API cost)

```bash
python chat.py
```

Supports English, Hindi (Devanagari), Gujarati, and Hinglish queries. Type `exit` to quit.

### Production Voice Server

```bash
uvicorn realtime_app:app --host 0.0.0.0 --port 8000
```

> ⚠️ Requires a running ngrok tunnel and Twilio webhook pointed to `https://<your-ngrok>.ngrok.io/incoming-call`.

## Paid APIs Used

| Component | Provider | Notes |
|---|---|---|
| STT | Sarvam AI | Charged per second of audio |
| LLM | Sarvam AI (`sarvam-105b`) | Charged per token |
| TTS | Sarvam AI (`bulbul:v3`) | Charged per character |
| Vector Storage | Pinecone | Free tier available |
| Telephony | Twilio | Charged per minute |

## Token Settings

| Setting | Value | Notes |
|---|---|---|
| `LLM_MAX_TOKENS` | 1200 | Buffer for sarvam-105b internal reasoning |
| `MAX_CONVERSATION_HISTORY` | 4 | Last 2 turns only |
| Pinecone `top_k` | 2 | 2 most relevant context chunks per query |
