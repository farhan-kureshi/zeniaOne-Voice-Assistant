# Testing Strategy

## Overview
Tests are located in the `tests/` directory.

## Testing Stack
- `pytest`: Primary test runner.
- `pytest-asyncio`: For testing asynchronous FastAPI and WebSocket functions.

## Guidelines
- Integration and smoke tests exist for the overall pipeline.
- Paid API tests (Sarvam, Twilio, Pinecone) should NOT be run automatically in CI to avoid excessive costs, and should be mocked or gated behind specific test markers.
- `chat.py` can be used as an end-to-end RAG validation tool without incurring voice transcription or synthesis costs.
