# Integrations

## Twilio
- Used for receiving inbound calls and routing audio streams via WebSockets.
- Essential Env Vars: `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER`, `NGROK_URL`.

## Sarvam AI
- **saarika:v2.5**: Streaming STT.
- **sarvam-105b**: Core LLM for multilingual reasoning.
- **bulbul:v3**: Streaming TTS.
- Essential Env Vars: `SARVAM_API_KEY`.

## Pinecone
- Used for RAG. Stores hospital knowledge documents.
- Essential Env Vars: `PINECONE_API_KEY`, `PINECONE_INDEX_NAME`.

## MongoDB
- Stores scheduled appointments and call logs.
- Essential Env Vars: `MONGODB_URI`.

## Google Sheets
- Secondary storage/export target for appointments.
- Essential Env Vars: `GOOGLE_SHEET_ID`.
