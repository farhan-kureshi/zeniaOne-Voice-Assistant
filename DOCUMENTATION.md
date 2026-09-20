# RK Hospital Voice Agent - Technical Documentation

## Table of Contents
1. [System Overview](#system-overview)
2. [Google File Search (RAG)](#google-file-search-rag)
3. [API Endpoints](#api-endpoints)
4. [RAG Trigger Keywords](#rag-trigger-keywords)
5. [Configuration](#configuration)
6. [Testing](#testing)
7. [Adding New Knowledge](#adding-new-knowledge)

---

## System Overview

### Architecture
```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Twilio Call   │────▶│  FastAPI Server │────▶│  Sarvam AI      │
│   (Media Stream)│     │  (realtime_app) │     │  (STT/TTS/LLM)  │
└─────────────────┘     └────────┬────────┘     └─────────────────┘
                                 │
                                 ▼
                        ┌─────────────────┐
                        │  Google Gemini  │
                        │  File Search    │
                        │  (RAG/Knowledge)│
                        └─────────────────┘
```

### Key Components
| Component | File | Purpose |
|-----------|------|---------|
| Main App | [realtime_app.py](realtime_app.py) | FastAPI server, WebSocket handling, call flow |
| RAG Module | [google_file_search.py](modules/google_file_search.py) | Google File Search integration |
| LLM Client | [llm_client.py](modules/llm_client.py) | Sarvam LLM API calls |
| TTS | [sarvam_tts.py](modules/sarvam_tts.py) | Text-to-Speech - converts text to audio |
| STT | [sarvam_stt.py](modules/sarvam_stt.py) | Speech-to-Text - streaming + batch fallback |
| Config | [config.py](config.py) | All configuration settings |
| Knowledge | [knowledge_docs/](knowledge_docs/) | Hospital documents for RAG |

---

## Google File Search (RAG)

### What is File Search?
Google's File Search (Semantic Retrieval) automatically:
- Chunks your documents
- Creates embeddings
- Stores in a vector database
- Retrieves relevant context for queries

### Current Setup
- **Store Name**: `rk-hospital-knowledge`
- **Store ID**: `fileSearchStores/rkhospitalknowledge-a0qqo8cfw8ye`
- **Model**: `gemini-2.5-flash`
- **Documents Indexed**: 3 files

### Indexed Documents
| File | Content |
|------|---------|
| [hospital_faqs.txt](knowledge_docs/hospital_faqs.txt) | Timings, departments, general info |
| [pricing_guide.txt](knowledge_docs/pricing_guide.txt) | Consultation fees, test costs, room charges |
| [doctor_schedule.txt](knowledge_docs/doctor_schedule.txt) | Doctor availability and timings |

### How RAG Works in Calls
1. User asks: "எவ்ளோ சார்ஜஸ் ஆகும்?" (How much charges?)
2. System detects keyword `சார்ஜஸ்` → triggers RAG
3. Gemini searches knowledge base
4. Returns Tamil response: "பொதுவான மருத்துவ ஆலோசனைக்கான கட்டணம் ₹300 முதல் ₹500..."
5. Sarvam LLM uses this context to answer

### Multilingual Support
RAG now returns responses in the user's language:
- **Tamil (ta-IN)**: Returns தமிழ் script
- **Hindi (hi-IN)**: Returns हिंदी script
- **Telugu (te-IN)**: Returns తెలుగు script
- **English (en-IN)**: Returns English

---

## API Endpoints

### Base URL
```
http://localhost:7000
```
Or via ngrok: `https://your-ngrok-url.ngrok-free.app`

### Call Management

#### 1. Make Outbound Call
```http
POST /make_call?phone_number=+919944559392
```
**Response:**
```json
{
  "status": "success",
  "call_sid": "CA06dfae6644a7964b6881219a4b79ba3c",
  "to": "+919944559392"
}
```

#### 2. Get Call Status
```http
GET /call_status/{call_sid}
```

#### 3. End Call
```http
POST /end_call/{call_sid}
```

### Knowledge Management

#### 4. Upload Knowledge Document
```http
POST /upload_knowledge
Content-Type: multipart/form-data

file: <file>
description: "Hospital pricing information"
```
**Response:**
```json
{
  "status": "success",
  "message": "File uploaded and indexed",
  "document_name": "pricing_guide.txt"
}
```

#### 5. Get Knowledge Status
```http
GET /knowledge_status
```
**Response:**
```json
{
  "status": "success",
  "store_name": "fileSearchStores/rkhospitalknowledge-a0qqo8cfw8ye",
  "documents": [
    {"name": "hospital_faqs.txt", "status": "indexed"},
    {"name": "pricing_guide.txt", "status": "indexed"},
    {"name": "doctor_schedule.txt", "status": "indexed"}
  ]
}
```

#### 6. Search Knowledge Base
```http
POST /search_knowledge
Content-Type: application/json

{
  "query": "What is the consultation fee?",
  "language": "ta-IN"
}
```
**Response:**
```json
{
  "status": "success",
  "answer": "பொதுவான மருத்துவ ஆலோசனைக்கான கட்டணம் ₹300 முதல் ₹500 வரை...",
  "search_time": 3.73
}
```

#### 7. Delete Knowledge Store
```http
DELETE /delete_knowledge_store
```
⚠️ **Warning**: This deletes ALL indexed documents!

### Twilio Webhooks (Internal)

| Endpoint | Purpose |
|----------|---------|
| `POST /outbound_voice` | TwiML for outbound calls |
| `POST /inbound_voice` | TwiML for inbound calls |
| `POST /call_status` | Call status callbacks |
| `WS /media-stream` | WebSocket for audio streaming |

### Health & Monitoring

#### 8. Health Check
```http
GET /health
```

#### 9. Get Active Sessions
```http
GET /sessions
```

---

## RAG Trigger Keywords

RAG is only triggered when user asks about specific topics (to save API costs and latency).

### English Keywords
```python
# Pricing
'cost', 'price', 'fee', 'charge', 'rate', 'how much', 'payment', 'insurance',
'consultation fee', 'test cost', 'room charge', 'bill', 'expense'

# Doctor/Schedule
'available', 'timing', 'schedule', 'when is', 'which doctor', 'specialist',
'dr.', 'doctor available', 'appointment time', 'open', 'closed', 'working hours'

# Services
'services', 'facilities', 'departments', 'tests', 'scan', 'x-ray', 'mri', 'ct',
'blood test', 'ecg', 'ultrasound', 'lab', 'pharmacy', 'ambulance'

# Hospital Info
'address', 'location', 'where', 'parking', 'directions', 'landmark'
```

### Tamil Keywords (தமிழ்)
```python
# Pricing
'எவ்வளவு', 'விலை', 'கட்டணம்', 'செலவு', 'ஃபீஸ்', 'பணம்', 'ரேட்',
'சார்ஜ்', 'சார்ஜஸ்', 'பிரைஸ்', 'பிரைசிங்', 'காஸ்ட்', 'ஃபீ'

# Doctor/Schedule (native + transliterated)
'டாக்டர்', 'மருத்துவர்', 'எப்போ', 'நேரம்', 'இருக்காங்களா',
'டைமிங்', 'ஷெட்யூல்', 'ஷெட்யூல்ஸ்',  # Transliterated timing/schedule
'அவைலபிலிட்டி', 'அவைலபில்',  # Transliterated availability
'செக்கப்', 'செக்-அப்', 'checkup'

# Services
'டெஸ்ட்', 'ஸ்கேன்', 'எக்ஸ்ரே', 'ரத்த பரிசோதனை', 'ஜெனரல்'

# Hospital Info
'எங்க', 'பார்க்கிங்'
```

### What Doesn't Trigger RAG
- Greetings: "வணக்கம்", "hello"
- Names: "என் பேரு ராஜ்"
- Simple confirmations: "சரி", "ok"
- Appointment booking flow (unless asking about fees)

---

## Configuration

### Environment Variables (.env)
```env
# Sarvam AI
SARVAM_API_KEY=your_sarvam_api_key

# Twilio
TWILIO_ACCOUNT_SID=your_twilio_sid
TWILIO_AUTH_TOKEN=your_twilio_token
TWILIO_PHONE_NUMBER=+14454474465

# MongoDB
MONGODB_URI=mongodb+srv://user:pass@cluster.mongodb.net/

# Google (for RAG)
GOOGLE_API_KEY=your_google_api_key

# Optional
FILE_SEARCH_ENABLED=true
FILE_SEARCH_STORE_NAME=rk-hospital-knowledge
```

### Config Settings ([config.py](config.py))
```python
# File Search Settings
FILE_SEARCH_ENABLED = True
FILE_SEARCH_STORE_NAME = "rk-hospital-knowledge"
FILE_SEARCH_MODEL = "gemini-2.5-flash"

# Server Settings
SERVER_PORT = 7000
```

---

## Testing

### 1. Test RAG Directly (Python)
```python
from modules.google_file_search import get_relevant_context

# English query
result = get_relevant_context("consultation fee")
print(result)

# Tamil query with Tamil response
result = get_relevant_context(
    "டாக்டர் fees எவ்ளோ?",
    response_language="ta-IN"
)
print(result)
```

### 2. Test via CLI
```bash
# Check knowledge status
python upload_knowledge.py --status

# Test search
python upload_knowledge.py --test "What is the consultation fee?"

# Upload new document
python upload_knowledge.py knowledge_docs/new_file.txt
```

### 3. Test via API (curl)
```bash
# Search knowledge
curl -X POST http://localhost:7000/search_knowledge \
  -H "Content-Type: application/json" \
  -d '{"query": "consultation fee", "language": "ta-IN"}'

# Upload document
curl -X POST http://localhost:7000/upload_knowledge \
  -F "file=@new_document.txt" \
  -F "description=New hospital info"
```

### 4. Test via Web UI
Open: `http://localhost:7000/call_trigger/knowledge_manager.html`

Features:
- Upload documents
- Check store status
- Search knowledge base
- Delete store

### 5. Make Test Call
```bash
curl -X POST "http://localhost:7000/make_call?phone_number=+919944559392"
```

---

## Adding New Knowledge

### Method 1: File Upload (Recommended)
1. Create a `.txt` file with your content
2. Upload via API or Web UI
3. Wait for indexing (30-60 seconds)

### Method 2: CLI Tool
```bash
# Single file
python upload_knowledge.py knowledge_docs/new_info.txt

# Multiple files
python upload_knowledge.py knowledge_docs/*.txt

# Create sample files
python upload_knowledge.py --create-samples
```

### Document Format Best Practices
```
# Document Title

## Section 1: Topic Name
Q: Common question?
A: Clear answer with specific details.

## Section 2: Another Topic
- Point 1: Details
- Point 2: More details
- Point 3: Even more details

Note: Any important notes or disclaimers.
```

### Supported File Types
- `.txt` - Plain text (recommended)
- `.md` - Markdown
- `.pdf` - PDF documents
- `.docx` - Word documents
- `.html` - HTML files

---

## Troubleshooting

### RAG Not Triggering
1. Check if `FILE_SEARCH_ENABLED=true` in `.env`
2. Verify keyword is in `RAG_TRIGGER_KEYWORDS` list
3. Check logs for `🔍 RAG triggered` message

### RAG Returns English Instead of Tamil
1. Ensure `response_language` is being passed
2. Check logs for `Response Language: Tamil (தமிழ்)`

### Google API Errors
1. Verify `GOOGLE_API_KEY` is set correctly
2. Check quota limits in Google Cloud Console
3. Ensure File Search API is enabled

### No Documents Found
```bash
# Check store status
python upload_knowledge.py --status

# Re-upload documents
python upload_knowledge.py knowledge_docs/*.txt
```

---

## Quick Reference

### Start Server
```bash
uv run python realtime_app.py
```

### Check Logs for RAG
Look for these in logs:
```
🔍 RAG triggered for: 'எவ்ளோ சார்ஜஸ்...'
   Response Language: Tamil (தமிழ்)
✅ RAG context retrieved (250 chars) in 3.5s
   📝 RAG Response: பொதுவான மருத்துவ...
```

### Key Files
| File | Purpose |
|------|---------|
| [realtime_app.py](realtime_app.py) | Main server |
| [google_file_search.py](modules/google_file_search.py) | RAG module |
| [config.py](config.py) | Configuration |
| [upload_knowledge.py](upload_knowledge.py) | CLI tool |
| [knowledge_docs/](knowledge_docs/) | Documents folder |
| `.env` | API keys |

---

## Contact & Support

For issues or feature requests, check the logs first:
1. `🔍` - RAG triggered
2. `✅` - Success
3. `⚠️` - Warning (non-fatal)
4. `❌` - Error

---

*Last Updated: December 26, 2025*
