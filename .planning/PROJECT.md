# RK Hospital Voice Agent

## Goal
A real-time multilingual voice agent for RK Hospital. Handles patient queries and appointment booking over phone calls using Twilio, Sarvam AI, and Pinecone.

## Description
Production-ready AI calling agent that leverages Sarvam AI's STT (saarika), LLM (sarvam-105b), and TTS (bulbul) along with Pinecone vector search for RAG-based hospital knowledge retrieval.

## Scope
- Inbound and outbound phone calls (via Twilio Media Streams)
- Real-time multilingual conversational AI (English, Hindi, Gujarati, Hinglish)
- Knowledge retrieval (RAG) using hospital documents
- Appointment booking integration (MongoDB / Google Sheets)
