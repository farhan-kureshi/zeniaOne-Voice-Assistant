# Sarvam Voice Agent - Comprehensive Guide

**Repository:** SrinathS-21/Sarvam-Voice-Agent  
**Language:** Python (93.2%), HTML (6.8%)  
**Last Updated:** December 26, 2025

> 📌 **Multi-Branch Documentation** - This guide consolidates content from all branches: `main` and `realtime`

---

## 📊 Branch Overview

| Branch | Status | Focus | Latest Commit |
|--------|--------|-------|---|
| **main** | Active | Main development branch | a358c0b |
| **realtime** | Active | Real-time streaming features | 58b11aa |

> Both branches maintain identical documentation with the same implementation approach.

---

## 🎯 Project Summary

**RK Hospital Voice Agent** - An AI-powered multilingual voice assistant for hospital appointment booking.

**Key Highlights:**
- 🎤 **Sub-1-second latency** real-time voice calls
- 🌍 **Multilingual support:** Tamil, Hindi, Telugu, English
- 🤖 **AI Technologies:** Sarvam AI (STT/TTS/LLM), Google Gemini RAG, Twilio Media Streams
- 💾 **Database:** MongoDB for appointment management
- 📋 **Integration:** Google Sheets for automatic appointment logging

---

## 🎯 Key Features

### Voice Capabilities
- 📞 **Real-time Voice Calls** - Inbound & outbound calls via Twilio Media Streams
- ⚡ **Sub-1s Latency** - Streaming STT + Streaming LLM + Streaming TTS pipeline
- 🎤 **Accurate Tamil STT** - Sarvam AI saarika:v2.5 model with VAD (Voice Activity Detection)
- 🗣️ **Natural TTS** - Sarvam AI bulbul:v2 with pronunciation normalization
- 🤖 **Intelligent LLM** - Sarvam-m model optimized for Tamil/English
- 🎵 **Background Audio** - Ambient audio to mask processing latency

### Hospital Features
- 📅 **Appointment Booking** - Complete booking flow with doctor suggestions
- 📋 **Google Sheets Integration** - Auto-save confirmed appointments
- ⏰ **Automated Reminders** - 1-hour before appointment reminder calls
- 📊 **Smart Data Extraction** - LLM-based appointment info extraction
- 🔍 **Knowledge Base (RAG)** - Google Gemini File Search for hospital info
- 🗓️ **Appointment Scheduling** - APScheduler for background job management

### Language Support
- 🌍 **Multilingual** - Tamil, Hindi, Telugu, English
- 🔤 **Native Script Output** - தமிழ், हिंदी, తెలుగు (no transliteration)
- 🗣️ **Pronunciation Fixes** - Abbreviations (RK → ஆர் கே), Times (4:00 → 4 மணி)
- 🧠 **Smart RAG in Native Language** - Gemini returns responses in user's language

---

## 🏗️ Architecture

```
┌────────────────────────────────────────────────────────────────────────────┐
│                    REAL-TIME STREAMING PIPELINE                          │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   Twilio          WebSocket         Sarvam            Sarvam            │
│   Media  ───────► Media    ───────► Streaming ──────► Streaming         │
│   Stream          Handler           STT               LLM               │
│   (mulaw)         (8kHz)            (VAD)             (sarvam-m)        │
│                                                                          │
│                     │                                    │               │
│                     ▼                                    ▼               │
│              ┌─────────────┐                      ┌─────────────┐       │
│              │   Google    │                      │  Streaming  │       │
│              │   Gemini    │ ◄─── RAG Trigger ───│    TTS      │       │
│              │ File Search │                      │  (bulbul)   │       │
│              └─────────────┘                      └─────────────┘       │
│                                                          │               │
│   Twilio  ◄─────── mulaw   ◄─────── mp3     ◄───────────┘              │
│   Playback         convert           audio                              │
│                                                                          │
│   Target Latency: < 1 second (User speech end → Agent speech start)     │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## 📁 Project Structure

```
Sarvam-Voice-Agent/
├── realtime_app.py           # Main FastAPI app (real-time streaming)
├── config.py                 # Configuration & system prompts
├── requirements.txt          # Python dependencies
├── pyproject.toml            # Project metadata
├── upload_knowledge.py       # CLI tool for document management
├── DOCUMENTATION.md          # Full technical documentation
├── COMPREHENSIVE_GUIDE.md    # This file - consolidated documentation
├── .env                      # Environment variables (create from .env.example)
│
├── modules/
│   ├── sarvam_tts.py         # Text-to-Speech (TTS) - converts text to audio
│   ├── sarvam_stt.py         # Speech-to-Text (STT) - streaming + batch
│   ├── llm_client.py         # LLM client with streaming + RAG support
│   ├── mongodb.py            # MongoDB operations & scheduling
│   ├── google_sheets.py      # Google Sheets webhook integration
│   ├── google_file_search.py # Google Gemini RAG integration
│   └── audio_utils.py        # Audio format conversion
│
├── knowledge_docs/           # Hospital knowledge base documents
│   ├── hospital_faqs.txt     # Timings, departments, general info
│   ├── pricing_guide.txt     # Consultation fees, test costs
│   └── doctor_schedule.txt   # Doctor availability
│
├── asset/
│   └── *.mp3                 # Background ambient audio file
│
└── call_trigger/
    ├── test_call.html        # Web UI for testing calls
    ├── knowledge_manager.html # Web UI for knowledge management
    ├── trigger_call.py       # Call triggering script
    └── README.md             # Call trigger documentation
```

---

## 🚀 Quick Start

### Prerequisites

1. **Python 3.10+** - [Download](https://www.python.org/downloads/)
2. **uv package manager** - `pip install uv`
3. **ffmpeg** - Required for audio processing
4. **ngrok** - For local development tunneling

### API Keys Required

| Service | Purpose | Get Key |
|---------|---------|---------|
| Sarvam AI | STT, TTS, LLM | [sarvam.ai](https://sarvam.ai) |
| Twilio | Voice calls | [twilio.com](https://www.twilio.com) |
| MongoDB Atlas | Database | [mongodb.com](https://www.mongodb.com/cloud/atlas) |
| Google AI | RAG/File Search | [aistudio.google.com](https://aistudio.google.com) |
| ngrok | Tunneling | [ngrok.com](https://ngrok.com) |

### Installation

```bash
# Clone repository
git clone https://github.com/SrinathS-21/Sarvam-Voice-Agent.git
cd Sarvam-Voice-Agent

# Checkout desired branch (main or realtime)
git checkout realtime  # or git checkout main

# Install dependencies
pip install uv
uv pip install -r requirements.txt

# Copy environment template
cp .env.example .env
# Edit .env with your API keys
```

### Environment Variables (.env)

```env
# Sarvam AI (STT, TTS, LLM)
SARVAM_API_KEY=your_sarvam_api_key

# Twilio
TWILIO_ACCOUNT_SID=your_account_sid
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_PHONE_NUMBER=+1234567890
PERSONAL_PHONE=+919876543210

# MongoDB
MONGODB_URI=mongodb+srv://user:pass@cluster.mongodb.net/
MONGODB_DB_NAME=rk_hospital

# Google AI (for RAG)
GOOGLE_API_KEY=your_google_api_key
FILE_SEARCH_ENABLED=true
FILE_SEARCH_STORE_NAME=rk-hospital-knowledge

# Google Sheets (Optional)
GOOGLE_SHEETS_WEBHOOK_URL=https://script.google.com/macros/s/xxx/exec

# ngrok URL (update after starting ngrok)
NGROK_URL=xxxxx.ngrok-free.app
```

### Running the Server

**Terminal 1 - Start ngrok:**
```bash
ngrok http 7000
# Copy the URL (e.g., https://abc123.ngrok-free.app)
# Update NGROK_URL in .env
```

**Terminal 2 - Start server:**
```bash
uv run python realtime_app.py
```

**Expected output:**
```
🔌 Connecting to MongoDB...
✅ MongoDB connected successfully to database: rk_hospital
🎵 Loading background ambient audio...
✅ Background audio loaded: 5676 chunks, 113.5s duration, -12dB volume
============================================================
🚀 REAL-TIME VOICE AGENT
============================================================
Mode: Twilio Media Streams + Sarvam WebSocket APIs
Target: Sub-1-second latency
============================================================
⏰ APScheduler started - background jobs active
INFO:     Uvicorn running on http://0.0.0.0:7000
```

---

## 📡 API Endpoints

### Health & Status

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Service health check |
| GET | `/health` | Simple health status |
| GET | `/sessions` | Active call sessions |

### Voice Calls

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/make_call?phone_number=+91xxx` | Initiate outbound call |
| POST | `/inbound_voice` | Twilio webhook for inbound calls |
| POST | `/outbound_voice` | Twilio webhook for outbound calls |
| POST | `/reminder_voice/{schedule_id}` | Webhook for reminder calls |
| POST | `/call_status` | Twilio call status callback |
| WS | `/media-stream` | Real-time audio WebSocket |

### Knowledge Management (RAG)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/upload_knowledge` | Upload document to knowledge base |
| GET | `/knowledge_status` | List indexed documents |
| POST | `/search_knowledge` | Search knowledge base |
| DELETE | `/delete_knowledge_store` | Delete all indexed documents |

### Scheduled Calls

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/schedule_call` | Schedule a future call |
| GET | `/scheduled_calls` | List all scheduled calls |
| DELETE | `/scheduled_calls/{id}` | Cancel a scheduled call |

### Example API Usage

**Make a Call:**
```bash
# Via curl
curl -X POST "http://localhost:7000/make_call?phone_number=%2B919876543210"

# Via browser
http://localhost:7000/call_trigger/test_call.html
```

**Search Knowledge Base:**
```bash
curl -X POST "http://localhost:7000/search_knowledge" \
  -H "Content-Type: application/json" \
  -d '{"query": "consultation fee", "language": "ta-IN"}'
```

**Response (in Tamil):**
```json
{
  "status": "success",
  "answer": "பொதுவான மருத்துவ ஆலோசனைக்கான கட்டணம் ₹300 முதல் ₹500 வரை...",
  "search_time": 3.73
}
```

---

## 🔍 RAG (Knowledge Base)

### How It Works

1. **Upload documents** to Google Gemini File Search
2. **Smart triggering** - RAG only activates for pricing/doctor/timing queries
3. **Multilingual responses** - Gemini returns answers in user's language (Tamil/Hindi/Telugu)
4. **Context injection** - RAG response is injected into Sarvam LLM prompt

### RAG Trigger Keywords

RAG is triggered when user asks about:
- **Pricing**: "charges", "fees", "எவ்ளோ", "சார்ஜஸ்", "கட்டணம்"
- **Doctors**: "doctor", "timing", "டாக்டர்", "நேரம்"
- **Services**: "checkup", "test", "scan", "செக்கப்"
- **Hospital info**: "address", "location", "எங்க"

### Managing Knowledge

```bash
# Check status
python upload_knowledge.py --status

# Upload new document
python upload_knowledge.py knowledge_docs/new_file.txt

# Test search
python upload_knowledge.py --test "What is consultation fee?"

# Web UI
http://localhost:7000/call_trigger/knowledge_manager.html
```

---

## ⚙️ Configuration

### Key Settings (config.py)

```python
# Language
DEFAULT_LANGUAGE = 'ta-IN'        # Tamil default
SUPPORTED_LANGUAGES = ['ta-IN', 'hi-IN', 'te-IN', 'en-IN']

# LLM
LLM_MODEL = 'sarvam-m'            # Sarvam's multilingual model
LLM_MAX_TOKENS = 60               # Short responses for speed
LLM_TEMPERATURE = 0.3             # Consistent responses

# RAG
FILE_SEARCH_ENABLED = True
FILE_SEARCH_MODEL = 'gemini-2.5-flash'
FILE_SEARCH_STORE_NAME = 'rk-hospital-knowledge'

# Hospital
HOSPITAL_NAME = "RK Hospital"
HOSPITAL_TIMINGS = "Monday to Saturday, 9:00 AM to 9:00 PM"
```

---

## 🔧 Background Jobs

| Job | Frequency | Description |
|-----|-----------|-------------|
| `execute_scheduled_calls` | Every 1 min | Executes due scheduled calls |
| `schedule_reminders` | Every 1 hour | Creates reminder calls for appointments |
| `cleanup_old_calls` | Daily | Removes old call records (30+ days) |

---

## 📊 Google Sheets Integration

Appointments are automatically saved to Google Sheets:

| Column | Description |
|--------|-------------|
| Timestamp | Call date/time |
| Patient Name | Extracted from conversation |
| Doctor/Department | Recommended specialist |
| Preferred Date/Time | Requested appointment time |
| Phone Number | Patient's phone |
| Reason for Visit | Symptoms/reason |

---

## 📞 Call Trigger - Test System

### Quick Start

**Prerequisites:** Ensure ngrok, FastAPI, and Twilio webhook are configured.

### Method 1: Web Interface (Easiest)

1. Open `call_trigger/test_call.html` in your browser
2. Enter your phone number (with country code)
3. Click "📞 Call Me Now"
4. Answer your phone!

### Method 2: Python Script

```bash
# Basic usage (default number)
python call_trigger/trigger_call.py

# Custom number
python call_trigger/trigger_call.py +919876543210
```

### Method 3: Direct API Call

**Browser:**
```
http://localhost:7000/make_call?phone_number=+919876543210
```

**PowerShell:**
```powershell
curl -X POST "http://localhost:7000/make_call?phone_number=%2B919876543210"
```

### Phone Number Format

**Must include country code:**

| Country | Format | Example |
|---------|--------|---------|
| 🇮🇳 India | +91XXXXXXXXXX | +919944559392 |
| 🇺🇸 USA | +1XXXXXXXXXX | +12025551234 |
| 🇬🇧 UK | +44XXXXXXXXXX | +447911123456 |
| 🇦🇺 Australia | +61XXXXXXXXX | +61412345678 |
| 🇨🇦 Canada | +1XXXXXXXXXX | +14165551234 |

### Call Flow

1. **Your phone rings** (5-10 seconds after trigger)
2. **Answer the call**
3. **AI greets you:** "Welcome to RK Hospital..."
4. **Conversation flow:**
   - AI asks for your name
   - AI asks which doctor you need
   - AI asks for appointment date/time
   - AI asks for phone number
   - AI asks for reason for visit
   - AI confirms all details
5. **Say "goodbye" or "thank you"**
6. **Appointment saved** to MongoDB + Google Sheets

---

## 🐛 Troubleshooting

### RAG not triggering
```bash
# Check FILE_SEARCH_ENABLED=true in .env
# Verify keyword is in RAG_TRIGGER_KEYWORDS
# Look for "🔍 RAG triggered" in logs
```

### Call connects but no audio
```bash
# Check ngrok is running and URL is updated in .env
ngrok http 7000
# Update NGROK_URL in .env with the new URL
```

### TTS pronunciation issues
- Abbreviations like "RK" are auto-normalized to "ஆர் கே"
- Times like "4:00" become "4 மணி"

### Weird farewell response
- Check system prompt in `config.py`
- Ensure `FAREWELL_MESSAGES` templates are correct

### Connection Error
```bash
# Check if FastAPI is running
curl http://localhost:7000

# If not, start it:
uv run python realtime_app.py
```

### Call not connecting
**Checklist:**
- [ ] ngrok is running
- [ ] FastAPI is running
- [ ] Twilio webhook updated with ngrok URL
- [ ] Phone number has correct format (+country_code)
- [ ] Twilio account has credits for outbound calls

### Invalid phone number
**Solution:**
- Must start with `+`
- Must include country code
- No spaces or dashes
- Example: `+919944559392` ✅ not `9944559392` ❌

---

## 📊 Logs to Check

```bash
# Server logs show:
📞 NEW CALL: +919876543210
🎙️ Stream started: MZxxxxxxxx
🎵 Background audio playing: 500 chunks sent (10s)
👤 User: 'எனக்கு தலைவலி'
🔍 RAG triggered for: 'charges evlo...'
   Response Language: Tamil (தமிழ்)
✅ RAG context retrieved (250 chars) in 3.5s
✅ Response: சரி, உங்க பேரு என்ன?... | Latency: 1200ms
```

---

## 📈 Performance Targets

| Metric | Target | Typical |
|--------|--------|---------|
| STT Latency | < 500ms | 300-800ms |
| LLM Latency | < 800ms | 500-1200ms |
| TTS Latency | < 500ms | 300-600ms |
| RAG Latency | < 4s | 3-5s |
| **Total Turn** | **< 1.5s** | **1.0-1.8s** |

---

## 🚀 Deployment

### Docker

```dockerfile
FROM python:3.12-slim

RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install uv && uv pip install --system -r requirements.txt

COPY . .

EXPOSE 7000
CMD ["python", "realtime_app.py"]
```

**Build and Run:**
```bash
docker build -t rk-hospital-voice-agent .
docker run -p 7000:7000 --env-file .env rk-hospital-voice-agent
```

### Production Checklist

- [ ] Use environment variables for all secrets
- [ ] Configure proper Twilio webhook URLs
- [ ] Whitelist server IP in MongoDB Atlas
- [ ] Enable Google API key restrictions
- [ ] Upload knowledge documents
- [ ] Configure HTTPS (required for Twilio)
- [ ] Set up error monitoring
- [ ] Test with real phone numbers
- [ ] Monitor call quality and latency metrics
- [ ] Set up backup and disaster recovery

---

## 💡 Tips

1. **Use HTML interface** for easiest call testing experience
2. **Check terminal logs** while testing calls for real-time debugging
3. **Twilio charges apply** for outbound calls (check balance)
4. **International calls** may cost more than domestic
5. **Test with your own number** first before calling patients
6. **Monitor RAG performance** for optimal knowledge base triggering
7. **Use background audio** to mask processing latency and improve UX

---

## 📊 Cost Estimates (Approximate)

| Call Type | Cost per Minute |
|-----------|----------------|
| India → India | ~₹1-2 |
| USA → India | ~$0.02-0.04 |
| India → USA | ~₹3-5 |

*Check your Twilio console for exact rates.*

---

## 🔗 Useful Links

- [Twilio Console](https://console.twilio.com)
- [Check Twilio Balance](https://console.twilio.com/us1/billing/manage-billing)
- [View Call Logs](https://console.twilio.com/us1/monitor/logs/calls)
- [Sarvam AI Docs](https://sarvam.ai)
- [Google AI Studio](https://aistudio.google.com)
- [MongoDB Atlas](https://www.mongodb.com/cloud/atlas)
- [FastAPI Docs](https://fastapi.tiangolo.com)

---

## 📚 Additional Documentation

For more detailed information, see:
- **[DOCUMENTATION.md](DOCUMENTATION.md)** - Full technical documentation
- **[call_trigger/README.md](call_trigger/README.md)** - Call trigger guide
- **Branch-specific READMEs:**
  - `main` branch - Main development documentation
  - `realtime` branch - Real-time streaming features documentation

---

## 📄 License

MIT License - See LICENSE file for details

---

## 🙏 Acknowledgments

- [Sarvam AI](https://sarvam.ai) - Tamil/English STT, TTS, LLM
- [Google AI](https://ai.google.dev) - Gemini File Search (RAG)
- [Twilio](https://www.twilio.com) - Voice API & Media Streams
- [MongoDB](https://www.mongodb.com) - Database
- [FastAPI](https://fastapi.tiangolo.com) - Web framework
- [APScheduler](https://apscheduler.readthedocs.io/) - Background job scheduling

---

*Last Updated: December 26, 2025*  
*Repository: [SrinathS-21/Sarvam-Voice-Agent](https://github.com/SrinathS-21/Sarvam-Voice-Agent)*
