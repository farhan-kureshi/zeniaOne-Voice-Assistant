# Codebase Concerns & Risks

## Latency
- The end-to-end latency of STT -> RAG -> LLM -> TTS over WebSockets is a critical concern for voice agents.
- Need to monitor processing times within `realtime_app.py` and optimize chunk sizes for streaming text and audio.

## Cost Management
- Paid APIs (Sarvam, Twilio, Pinecone) are used for every voice call.
- Lack of rate limiting or DDOS protection could lead to unexpected costs if the Twilio webhook is exposed publicly without validation.

## Error Handling
- Robust error handling and fallback messages are required if the Sarvam APIs timeout or the Pinecone index is unreachable during a live call.
- Need to ensure Twilio connections are closed cleanly to avoid hanging calls and extra billing.
