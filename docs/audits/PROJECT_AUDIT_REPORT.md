# ZeniaOne Project Audit Report

## 1. Line Count Summary
- Total lines: 57758
- Backend lines: 15849
- Frontend lines: 34290
- Config lines: 8889
- Test lines: 674
- Docs lines: 2631

### Largest Files
- zenaipex-frontend/package-lock.json (8808 lines)
- zenaipex/ai/llm.py (1529 lines)
- zenaipex/api/v1/agents.py (1525 lines)
- zenaipex-frontend/components/ai-bot/voice-mode-overlay.tsx (1415 lines)
- modules/sarvam_stt.py (1038 lines)
- zenaipex-frontend/app/page.tsx (951 lines)
- zenaipex-frontend/lib/data/timezones.ts (915 lines)
- zenaipex-frontend/app/dashboard/my-ai/chat/page.tsx (895 lines)
- zenaipex-frontend/app/admin/my-ai/chat/page.tsx (862 lines)
- zenaipex-frontend/app/dashboard/settings/page.tsx (841 lines)

## 2. Architecture Map
```
Frontend (zenaipex-frontend) [Next.js, Tailwind, TypeScript]
  ↓ (REST / WebSockets)
API Gateway (zenaipex/api) [FastAPI]
  ↓
Backend Core (zenaipex/core, zenaipex/ai)
  ↓
Database (MongoDB) / Vector Store (Pinecone) / AI (Sarvam, Gemini, Groq, Nvidia)
```
