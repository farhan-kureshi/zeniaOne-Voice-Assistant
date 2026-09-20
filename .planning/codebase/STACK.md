# Tech Stack

## Core
- **Language**: Python >= 3.10
- **Web Framework**: FastAPI (with Uvicorn)
- **Environment Management**: python-dotenv, pydantic-settings

## AI & Data
- **Embeddings**: `sentence-transformers/all-MiniLM-L6-v2` via Pinecone
- **LLM/Speech**: Sarvam AI API (`sarvam-105b`, `saarika:v2.5`, `bulbul:v3`)
- **Database**: MongoDB (via `pymongo` and `motor`)

## Communications
- **Telephony**: Twilio (Media Streams over WebSockets)
- **Audio Processing**: FFmpeg (mu-law ↔ PCM)

## Dev & Tools
- **Testing**: `pytest`, `pytest-asyncio`
- **Formatting & Linting**: `black`, `ruff`, `mypy`
- **Package Management**: `uv` (recommended) or `pip`
