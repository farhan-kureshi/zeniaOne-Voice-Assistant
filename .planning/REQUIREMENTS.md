# Requirements

## Core Features
1. **Telephony Integration**: WebSocket-based media streaming with Twilio.
2. **Speech-to-Text**: Real-time transcription using Sarvam `saarika:v2.5`.
3. **Retrieval-Augmented Generation (RAG)**: Pinecone vector search with `sentence-transformers/all-MiniLM-L6-v2` embeddings for context retrieval.
4. **Large Language Model**: Multilingual reasoning and response generation via Sarvam `sarvam-105b`.
5. **Text-to-Speech**: Streaming audio generation using Sarvam `bulbul:v3`.
6. **Data Storage**: Scheduled call and appointment data stored in MongoDB.
7. **Offline Mode / Testing**: A terminal-based chatbot (`chat.py`) for validation without voice/telephony APIs.

## Non-Functional Requirements
- **Latency**: End-to-end voice latency must be minimized for natural conversation.
- **Multilingual Support**: Must natively handle English, Hindi (Devanagari), Gujarati, and Hinglish.
- **Cost Efficiency**: Optimize context token usage and buffer settings (`LLM_MAX_TOKENS = 1200`, `top_k = 2`, `MAX_CONVERSATION_HISTORY = 4`).
