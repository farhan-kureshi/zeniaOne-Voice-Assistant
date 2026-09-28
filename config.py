"""
Configuration module for AI Voice Call Agent.
Loads environment variables and provides centralized config access.
"""
import os
from typing import List
from dotenv import load_dotenv

load_dotenv()

# Twilio Configuration
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID', '')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN', '')
TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER', '')
PERSONAL_PHONE = os.getenv('PERSONAL_PHONE', '')
NGROK_URL = os.getenv('NGROK_URL', '')

# MongoDB Configuration
MONGODB_URI = os.getenv('MONGODB_URI', '')
MONGODB_DB_NAME = os.getenv('MONGODB_DB_NAME', 'spinabot_calls')

# Pinecone Configuration
PINECONE_API_KEY = os.getenv('PINECONE_API_KEY', '')
PINECONE_ENVIRONMENT = os.getenv('PINECONE_ENVIRONMENT', '')
PINECONE_INDEX_NAME = os.getenv('PINECONE_INDEX_NAME', 'hospital-knowledge')
PINECONE_DIMENSION = int(os.getenv('PINECONE_DIMENSION', '384'))

# Sarvam AI Configuration (Multilingual)
SARVAM_API_KEY = os.getenv('SARVAM_API_KEY', '')
SARVAM_API_URL = os.getenv('SARVAM_API_URL', 'https://api.sarvam.ai')

# REST API endpoints
SARVAM_STT_MODEL = os.getenv('SARVAM_STT_MODEL', 'saarika:v2.5')  # Latest model
SARVAM_TTS_MODEL = os.getenv('SARVAM_TTS_MODEL', 'bulbul:v3')
SARVAM_TTS_VOICE = os.getenv('SARVAM_TTS_VOICE', 'anushka')

# WebSocket endpoints for real-time streaming
SARVAM_STT_WS_URL = os.getenv('SARVAM_STT_WS_URL', 'wss://api.sarvam.ai/speech-to-text/ws')
SARVAM_TTS_WS_URL = os.getenv('SARVAM_TTS_WS_URL', 'wss://api.sarvam.ai/text-to-speech/ws')

# Supported Languages for Sarvam AI
# Only Tamil and English supported for now
DEFAULT_LANGUAGE = os.getenv('DEFAULT_LANGUAGE', 'ta-IN')  # Fixed to Tamil
SUPPORTED_LANGUAGES = ['ta-IN', 'en-IN']  # Tamil and English only

# Lock language switching - set to True to prevent automatic language changes
LOCK_LANGUAGE = True

# LLM Configuration (Sarvam AI - sarvam-m model for Indian languages)
LLM_API_KEY = os.getenv('SARVAM_API_KEY', '')  # Using Sarvam LLM (same key as STT/TTS)
LLM_API_URL = os.getenv('LLM_API_URL', 'https://api.sarvam.ai/v1')
LLM_MODEL = os.getenv('LLM_MODEL', 'sarvam-105b')  # Sarvam's multilingual model
LLM_MAX_TOKENS = int(os.getenv('LLM_MAX_TOKENS', '1200'))  # Required buffer for Sarvam <think> tokens
LLM_TEMPERATURE = float(os.getenv('LLM_TEMPERATURE', '0.3'))
LLM_TOP_P = float(os.getenv('LLM_TOP_P', '0.95'))

# Embedding Model Configuration
EMBEDDING_MODEL = os.getenv('EMBEDDING_MODEL', 'sentence-transformers/all-MiniLM-L6-v2')
EMBEDDING_DIMENSION = int(os.getenv('EMBEDDING_DIMENSION', '384'))

# Google Sheets Integration
GOOGLE_SHEETS_WEBHOOK_URL = os.getenv('GOOGLE_SHEETS_WEBHOOK_URL', '')

# Flask Configuration
FLASK_APP = os.getenv('FLASK_APP', 'app.py')
FLASK_ENV = os.getenv('FLASK_ENV', 'development')
FLASK_DEBUG = os.getenv('FLASK_DEBUG', 'True').lower() == 'true'

# Application Settings - OPTIMIZED FOR SPEED
SESSION_TIMEOUT_MINUTES = int(os.getenv('SESSION_TIMEOUT_MINUTES', '30'))
MAX_CONVERSATION_HISTORY = int(os.getenv('MAX_CONVERSATION_HISTORY', '4'))  # Reduced to save tokens
ENABLE_CRISIS_DETECTION = False  # Not needed for hospital booking
CRISIS_KEYWORDS: List[str] = []  # Empty for hospital system

# Hospital Configuration
HOSPITAL_NAME = "RK Hospital"
HOSPITAL_ADDRESS = "123 Main Road, Anna Nagar, Chennai, Tamil Nadu - 600040"
HOSPITAL_PHONE = "044-2626-XXXX"
HOSPITAL_TIMINGS = "Monday to Saturday, 9:00 AM to 6:00 PM (Closed on Sundays)"
HOSPITAL_EMERGENCY = "24/7 Emergency Services Available"
HOSPITAL_LANDMARK = "Near Anna Nagar Tower, Opposite City Mall"
AVAILABLE_DOCTORS = ["General Physician", "Cardiologist", "Dentist", "Orthopedic", "Pediatrician", "ENT Specialist"]

# Hospital Appointment Booking System Prompt (Dynamic Multilingual)
# Note: {user_language} and {current_date} will be replaced at runtime
HOSPITAL_SYSTEM_PROMPT = """You are RK Hospital's receptionist.
RULES:
1. MATCH USER'S SCRIPT (Eng->Eng, Devanagari->Devanagari, Gujarati->Gujarati, Hinglish->Hinglish).
2. Answer in 1-2 concise sentences MAX.
3. Keep internal reasoning <20 words.
4. STRICTLY use provided context. If unknown, say so. No guessing.
5. To book, ask: name, symptoms, preferred time.
6. End with: "Is there anything else I can help you with?" (in user's language)."""
