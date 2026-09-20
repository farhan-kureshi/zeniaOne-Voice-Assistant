# Directory Structure

```text
.
├── realtime_app.py       # FastAPI production server (Twilio + full voice pipeline)
├── config.py             # All configuration (loaded from .env)
├── chat.py               # Terminal RAG chatbot for testing
├── seed_knowledge.py     # Script to load hospital docs into Pinecone
├── pyproject.toml        # Project dependencies
├── requirements.txt      # Pip-compatible dependencies
├── modules/
│   ├── llm_client.py     # Sarvam-105B LLM interface + RAG helpers
│   ├── vector_store.py   # Pinecone singleton + similarity search
│   ├── sarvam_stt.py     # Sarvam STT (streaming WebSocket)
│   ├── sarvam_tts.py     # Sarvam TTS (streaming WebSocket, bulbul:v3)
│   ├── audio_utils.py    # mu-law ↔ PCM ↔ WAV conversion
│   ├── mongodb.py        # Appointment and scheduled call storage
│   └── google_sheets.py  # Appointment export to Google Sheets
├── knowledge_docs/       # Plain-text hospital knowledge files
├── call_trigger/         # Static web UI and scripts for outbound calls
└── tests/                # Integration and smoke tests
```
