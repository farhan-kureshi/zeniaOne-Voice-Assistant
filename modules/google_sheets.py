"""
Google Sheets Integration Module
Saves appointment details to Google Sheets for RK Hospital.
"""
import os
import json
import re
from datetime import datetime
from typing import Dict, Any, Optional, List
import requests
import config

# Google Sheets API configuration
GOOGLE_SHEETS_WEBHOOK_URL = os.getenv('GOOGLE_SHEETS_WEBHOOK_URL', '')


def extract_appointment_with_llm(conversation_history: List[Dict[str, str]]) -> Dict[str, Any]:
    """
    Use LLM to intelligently extract appointment details from conversation.
    This is more reliable than regex patterns for multilingual content.
    
    Args:
        conversation_history: List of conversation messages
    
    Returns:
        Dictionary with extracted appointment details in English
    """
    if not config.SARVAM_API_KEY:
        return {}
    
    # Build conversation text
    conversation_text = ""
    for msg in conversation_history:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "user":
            conversation_text += f"Patient: {content}\n"
        elif role == "assistant":
            conversation_text += f"Receptionist: {content}\n"
    
    if not conversation_text.strip():
        return {}
    
    extraction_prompt = f"""Extract appointment details from this hospital booking conversation.
Return ONLY a JSON object with these fields (use null if not found):
- patient_name: Full name in English (transliterate if in other language)
- doctor_type: One of [General Physician, Cardiologist, Dentist, Orthopedic, Pediatrician, ENT Specialist]
- date: In YYYY-MM-DD format (today is {datetime.now().strftime('%Y-%m-%d')}, tomorrow is {(datetime.now() + __import__('datetime').timedelta(days=1)).strftime('%Y-%m-%d')})
- time: In HH:MM AM/PM format
- reason: Brief reason for visit in English (transliterate if needed)
- additional_info: Any other relevant details mentioned

Conversation:
{conversation_text}

Return ONLY valid JSON, no explanation:"""

    try:
        print("🤖 Using LLM for smart data extraction...")
        
        response = requests.post(
            f"{config.SARVAM_API_URL}/v1/chat/completions",
            headers={
                "api-subscription-key": config.SARVAM_API_KEY,
                "Content-Type": "application/json"
            },
            json={
                "model": "sarvam-m",
                "messages": [
                    {"role": "system", "content": "You are a data extraction assistant. Extract information and return ONLY valid JSON."},
                    {"role": "user", "content": extraction_prompt}
                ],
                "max_tokens": 300,
                "temperature": 0.1  # Low temperature for consistent extraction
            },
            timeout=20
        )
        
        if response.status_code == 200:
            result = response.json()
            llm_response = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            
            # Parse JSON from response
            # Try to find JSON in the response
            json_match = re.search(r'\{[^{}]*\}', llm_response, re.DOTALL)
            if json_match:
                extracted = json.loads(json_match.group())
                print(f"✅ LLM Extracted: {extracted}")
                return extracted
            else:
                print(f"⚠️ Could not parse LLM response as JSON: {llm_response[:200]}")
                return {}
        else:
            print(f"⚠️ LLM extraction failed: {response.status_code}")
            return {}
            
    except Exception as e:
        print(f"⚠️ LLM extraction error: {e}")
        return {}


def transliterate_to_english(text: str, source_lang: str = "ta-IN") -> str:
    """
    Transliterate Indian language text to English using Sarvam API.
    
    Args:
        text: Text in Indian language
        source_lang: Source language code (ta-IN, hi-IN, te-IN, etc.)
    
    Returns:
        Transliterated English text
    """
    if not text or not config.SARVAM_API_KEY:
        return text
    
    # Check if text is already English (ASCII)
    if text.isascii():
        return text
    
    try:
        # Map language codes to Sarvam format
        lang_map = {
            'ta-IN': 'ta',
            'hi-IN': 'hi', 
            'te-IN': 'te',
            'kn-IN': 'kn',
            'ml-IN': 'ml',
            'mr-IN': 'mr',
            'gu-IN': 'gu',
            'bn-IN': 'bn',
            'pa-IN': 'pa',
            'or-IN': 'od'
        }
        
        source = lang_map.get(source_lang, 'ta')
        
        response = requests.post(
            f"{config.SARVAM_API_URL}/transliterate",
            headers={
                "api-subscription-key": config.SARVAM_API_KEY,
                "Content-Type": "application/json"
            },
            json={
                "input": text,
                "source_language_code": source,
                "target_language_code": "en"
            },
            timeout=10
        )
        
        if response.status_code == 200:
            result = response.json()
            transliterated = result.get("transliterated_text", text)
            print(f"🔤 Transliterated: '{text}' → '{transliterated}'")
            return transliterated
        else:
            print(f"⚠️ Transliteration failed: {response.status_code}")
            return text
            
    except Exception as e:
        print(f"⚠️ Transliteration error: {e}")
        return text


def extract_name_from_text(text: str) -> Optional[str]:
    """
    Extract patient name from text using multiple patterns.
    Works with Tamil, Hindi, Telugu, and English.
    """
    # Tamil patterns - more comprehensive
    tamil_patterns = [
        r'(?:என்னுடைய பெயர்|என் பெயர்|என்பெயர்|பெயர்)\s*([அ-ஹா-ௌ\s]+)',
        r'(?:நான்|நாம்)\s*([அ-ஹா-ௌ\s]+)',
        r'([அ-ஹா-ௌ]+(?:\s+[அ-ஹா-ௌ]+)*)\s*(?:பேசுறேன்|பேசுகிறேன்)',
    ]
    
    # Hindi patterns
    hindi_patterns = [
        r'(?:मेरा नाम|मैं|नाम)\s+([अ-ह\s]+)',
    ]
    
    # Telugu patterns
    telugu_patterns = [
        r'(?:నా పేరు|నేను)\s+([అ-హ\s]+)',
    ]
    
    # English patterns
    english_patterns = [
        r'(?:my name is|i am|i\'m|name is|this is|call me)\s+([a-zA-Z\s]+?)(?:\.|,|$|\s+i\s|\s+and\s|\s+want)',
        r'^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s*$',  # Just a name
    ]
    
    all_patterns = tamil_patterns + hindi_patterns + telugu_patterns + english_patterns
    
    for pattern in all_patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.UNICODE)
        if match:
            name = match.group(1).strip()
            # Clean up
            name = re.sub(r'\s+', ' ', name)
            # Filter out common non-name words
            skip_words = ['doctor', 'appointment', 'book', 'want', 'need', 'டாக்டர்', 'अपॉइंटमेंट']
            if len(name) > 1 and len(name) < 50 and not any(w in name.lower() for w in skip_words):
                return name
    
    return None


def extract_appointment_info(conversation_history: list) -> Dict[str, Any]:
    """
    Extract appointment information from conversation history.
    Uses LLM for intelligent extraction, falls back to regex patterns.
    
    Args:
        conversation_history: List of conversation messages
    
    Returns:
        Dictionary with extracted appointment details (in English)
    """
    appointment_data = {
        "name": None,
        "doctor": None,
        "date_time": None,
        "phone": None,
        "reason": None,
        "additional_info": None,
        "timestamp": datetime.now().isoformat()
    }
    
    # Try LLM extraction first (more accurate for multilingual)
    llm_extracted = extract_appointment_with_llm(conversation_history)
    
    if llm_extracted:
        # Map LLM extracted fields
        if llm_extracted.get("patient_name"):
            appointment_data["name"] = llm_extracted["patient_name"]
        if llm_extracted.get("doctor_type"):
            appointment_data["doctor"] = llm_extracted["doctor_type"]
        if llm_extracted.get("date") or llm_extracted.get("time"):
            date_part = llm_extracted.get("date", "")
            time_part = llm_extracted.get("time", "")
            appointment_data["date_time"] = f"{date_part} {time_part}".strip()
        if llm_extracted.get("reason"):
            appointment_data["reason"] = llm_extracted["reason"]
        if llm_extracted.get("additional_info"):
            appointment_data["additional_info"] = llm_extracted["additional_info"]
    
    # Fall back to regex extraction for any missing fields
    if not all([appointment_data["name"], appointment_data["doctor"], appointment_data["date_time"]]):
        regex_extracted = extract_appointment_info_regex(conversation_history)
        
        # Fill in missing fields from regex
        if not appointment_data["name"] and regex_extracted.get("name"):
            appointment_data["name"] = regex_extracted["name"]
        if not appointment_data["doctor"] and regex_extracted.get("doctor"):
            appointment_data["doctor"] = regex_extracted["doctor"]
        if not appointment_data["date_time"] and regex_extracted.get("date_time"):
            appointment_data["date_time"] = regex_extracted["date_time"]
        if not appointment_data["reason"] and regex_extracted.get("reason"):
            appointment_data["reason"] = regex_extracted["reason"]
    
    # Store raw conversation for manual review
    conversation_text = ""
    for msg in conversation_history:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "user":
            conversation_text += f"Patient: {content}\n"
        elif role == "assistant":
            conversation_text += f"AI: {content}\n"
    
    appointment_data["raw_conversation"] = conversation_text[:1000]
    
    print(f"📋 Final Extracted: Name={appointment_data['name']}, Doctor={appointment_data['doctor']}, DateTime={appointment_data['date_time']}, Reason={appointment_data['reason']}")
    
    return appointment_data


def extract_appointment_info_regex(conversation_history: list) -> Dict[str, Any]:
    """
    Extract appointment information using regex patterns (fallback method).
    
    Args:
        conversation_history: List of conversation messages
    
    Returns:
        Dictionary with extracted appointment details (in English)
    """
    appointment_data = {
        "name": None,
        "doctor": None,
        "date_time": None,
        "phone": None,
        "reason": None,
        "additional_info": None,
        "timestamp": datetime.now().isoformat()
    }
    
    # Collect all user and assistant messages
    user_messages = []
    assistant_messages = []
    detected_language = "en-IN"
    
    for msg in conversation_history:
        role = msg.get("role", "")
        content = msg.get("content", "").strip()
        if role == "user":
            user_messages.append(content)
            # Detect language from Tamil/Hindi/Telugu characters
            if re.search(r'[அ-ஹ]', content):
                detected_language = "ta-IN"
            elif re.search(r'[अ-ह]', content):
                detected_language = "hi-IN"
            elif re.search(r'[అ-హ]', content):
                detected_language = "te-IN"
        elif role == "assistant":
            assistant_messages.append(content)
    
    all_text = " ".join(user_messages + assistant_messages).lower()
    user_text = " ".join(user_messages)
    
    # Extract Patient Name from each user message
    for msg in user_messages:
        name = extract_name_from_text(msg)
        if name:
            # Transliterate to English if not ASCII
            if not name.isascii():
                name = transliterate_to_english(name, detected_language)
            appointment_data["name"] = name.title()
            break
    
    # Also check assistant confirmations for name (LLM might repeat the name)
    if not appointment_data["name"]:
        for msg in assistant_messages:
            # Look for patterns like "So Sreenath," or "சரி ஸ்ரீநாத்,"
            name_confirm = re.search(r'(?:சரி|So|Ok|Dear)\s+([அ-ஹா-ௌa-zA-Z\s]+?)(?:,|அவர்|ji)', msg, re.IGNORECASE)
            if name_confirm:
                name = name_confirm.group(1).strip()
                if not name.isascii():
                    name = transliterate_to_english(name, detected_language)
                if len(name) > 1 and len(name) < 30:
                    appointment_data["name"] = name.title()
                    break
    
    # Extract Doctor Type
    doctor_types = {
        'general physician': 'General Physician',
        'general': 'General Physician',
        'cardiologist': 'Cardiologist',
        'heart': 'Cardiologist',
        'cardio': 'Cardiologist',
        'dentist': 'Dentist',
        'dental': 'Dentist',
        'teeth': 'Dentist',
        'orthopedic': 'Orthopedic',
        'ortho': 'Orthopedic',
        'bone': 'Orthopedic',
        'pediatrician': 'Pediatrician',
        'child': 'Pediatrician',
        'kids': 'Pediatrician',
        'ent': 'ENT Specialist',
        'ear': 'ENT Specialist',
        'nose': 'ENT Specialist',
        'throat': 'ENT Specialist',
        # Tamil
        'ஈஎன்டி': 'ENT Specialist',
        'இஎன்டி': 'ENT Specialist',
        'காது': 'ENT Specialist',
        'மூக்கு': 'ENT Specialist',
        'தொண்டை': 'ENT Specialist',
        'பொது': 'General Physician',
        'இதயம்': 'Cardiologist',
        'இருதயம்': 'Cardiologist',
        'பல்': 'Dentist',
        'எலும்பு': 'Orthopedic',
        'குழந்தை': 'Pediatrician',
        # Hindi
        'ईएनटी': 'ENT Specialist',
        'कान': 'ENT Specialist',
        'नाक': 'ENT Specialist',
        'गला': 'ENT Specialist',
        'हृदय': 'Cardiologist',
        'दिल': 'Cardiologist',
        'दांत': 'Dentist',
        'हड्डी': 'Orthopedic',
        'बच्चे': 'Pediatrician',
        # Telugu
        'చెవి': 'ENT Specialist',
        'ముక్కు': 'ENT Specialist',
        'గొంతు': 'ENT Specialist',
    }
    
    for keyword, doctor in doctor_types.items():
        if keyword in all_text:
            appointment_data["doctor"] = doctor
            break
    
    # Extract Reason for Visit
    reason_patterns = [
        # English
        r'(?:reason|problem|issue|for|because|suffering from|having)\s+(?:is\s+)?([a-zA-Z\s]+?)(?:\.|,|$)',
        r'(?:i have|having|got)\s+([a-zA-Z\s]+?)(?:\.|,|$|\s+(?:for|since))',
        # Tamil
        r'(?:காரணம்|பிரச்சனை|வலி)\s*([அ-ஹா-ௌa-zA-Z\s]+)',
        r'([அ-ஹா-ௌa-zA-Z\s]+)\s*(?:வலி|பிரச்சனை|இருக்கு)',
        # Hindi  
        r'(?:तकलीफ|दर्द|समस्या)\s+([अ-हa-zA-Z\s]+)',
    ]
    
    for pattern in reason_patterns:
        match = re.search(pattern, user_text, re.IGNORECASE)
        if match:
            reason = match.group(1).strip()
            if not reason.isascii():
                reason = transliterate_to_english(reason, detected_language)
            if len(reason) > 2 and len(reason) < 100:
                appointment_data["reason"] = reason
                break
    
    # Extract Date/Time
    date_time_parts = []
    
    # Tamil number words to digits
    tamil_numbers = {
        'ஒன்று': '1', 'ஒரு': '1',
        'இரண்டு': '2', 'ரெண்டு': '2',
        'மூன்று': '3',
        'நான்கு': '4',
        'ஐந்து': '5',
        'ஆறு': '6',
        'ஏழு': '7',
        'எட்டு': '8',
        'ஒன்பது': '9',
        'பத்து': '10',
        'பதினொரு': '11', 'பதினொன்று': '11',
        'பன்னிரண்டு': '12', 'பன்னெண்டு': '12', 'பன்னிரெண்டு': '12',
    }
    
    # Hindi number words
    hindi_numbers = {
        'एक': '1', 'दो': '2', 'तीन': '3', 'चार': '4', 'पांच': '5',
        'छह': '6', 'सात': '7', 'आठ': '8', 'नौ': '9', 'दस': '10',
        'ग्यारह': '11', 'बारह': '12',
    }
    
    # Date patterns
    if 'tomorrow' in all_text or 'நாளை' in all_text or 'कल' in all_text or 'రేపు' in all_text:
        from datetime import timedelta
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        date_time_parts.append(tomorrow)
    elif 'today' in all_text or 'இன்று' in all_text or 'आज' in all_text:
        date_time_parts.append(datetime.now().strftime("%Y-%m-%d"))
    
    # Convert Tamil/Hindi number words to digits in text
    processed_text = all_text
    for word, digit in {**tamil_numbers, **hindi_numbers}.items():
        processed_text = processed_text.replace(word, digit)
    
    # Time patterns (now works with converted numbers too)
    time_patterns = [
        r'(\d{1,2})\s*(?:am|a\.m\.|AM)',
        r'(\d{1,2})\s*(?:pm|p\.m\.|PM)',
        r'(\d{1,2})\s*(?:o\'?clock|மணி|बजे|గంట)',
        r'(?:morning|காலை|सुबह)\s*(\d{1,2})',
        r'(?:evening|மாலை|शाम)\s*(\d{1,2})',
        r'(\d{1,2}):(\d{2})',
    ]
    
    # Search in processed_text (with Tamil/Hindi numbers converted)
    for pattern in time_patterns:
        match = re.search(pattern, processed_text, re.IGNORECASE)
        if match:
            hour = match.group(1)
            # Determine AM/PM
            if 'pm' in processed_text.lower() or 'மாலை' in all_text or 'शाम' in all_text or 'evening' in processed_text.lower():
                time_str = f"{hour}:00 PM"
            elif int(hour) >= 9 and int(hour) <= 12:
                time_str = f"{hour}:00 AM"  # Morning hours
            else:
                time_str = f"{hour}:00 PM"  # Afternoon/evening hours
            date_time_parts.append(time_str)
            break
    
    if date_time_parts:
        appointment_data["date_time"] = " ".join(date_time_parts)
    
    return appointment_data


def save_appointment_to_sheets(appointment_data: Dict[str, Any]) -> bool:
    """
    Save appointment data to Google Sheets via webhook or API.
    Only saves CONFIRMED bookings with complete data.
    
    Args:
        appointment_data: Dictionary containing appointment details
    
    Returns:
        True if successful, False otherwise
    """
    try:
        if not GOOGLE_SHEETS_WEBHOOK_URL:
            print("Warning: GOOGLE_SHEETS_WEBHOOK_URL not configured. Skipping Google Sheets save.")
            return False
        
        # ============ SAFETY NET: Validate before sending to sheets ============
        name = appointment_data.get("name", "") or ""
        doctor = appointment_data.get("doctor", "") or ""
        date_time = appointment_data.get("date_time", "") or ""
        
        # Skip if any required field is missing/invalid
        if not name.strip() or name.strip().lower() == "none":
            print("⛔ Sheet save blocked: No valid patient name")
            return False
        if not doctor.strip() or doctor.strip().lower() == "none":
            print("⛔ Sheet save blocked: No valid doctor")
            return False
        if not date_time.strip() or "none" in date_time.lower() or len(date_time.strip()) < 3:
            print("⛔ Sheet save blocked: No valid date/time")
            return False
        
        # Prepare data for Google Sheets
        sheet_row = {
            "Timestamp": appointment_data.get("timestamp", datetime.now().isoformat()),
            "Patient Name": appointment_data.get("name", ""),
            "Doctor/Department": appointment_data.get("doctor", ""),
            "Preferred Date/Time": appointment_data.get("date_time", ""),
            "Phone Number": appointment_data.get("phone", ""),
            "Reason for Visit": appointment_data.get("reason", ""),
            "Additional Info": appointment_data.get("additional_info", ""),
            "Call SID": appointment_data.get("call_sid", ""),
            "Status": "Pending Confirmation"
        }
        
        # Send to Google Sheets webhook (Google Apps Script or Zapier/Make.com)
        response = requests.post(
            GOOGLE_SHEETS_WEBHOOK_URL,
            json=sheet_row,
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        
        if response.status_code == 200:
            print(f"✓ Appointment saved to Google Sheets: {sheet_row['Patient Name']}")
            return True
        else:
            print(f"✗ Failed to save to Google Sheets: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"Error saving to Google Sheets: {e}")
        return False


def save_appointment_to_mongodb_and_sheets(
    user_phone: str,
    appointment_details: Dict[str, Any],
    session_id: str,
    conversation_history: list
) -> bool:
    """
    Save appointment to both MongoDB and Google Sheets.
    Only saves to Google Sheets if there's actual booking data (not empty/cancelled calls).
    
    Args:
        user_phone: Caller's phone number
        appointment_details: Extracted appointment information
        session_id: Session ID from MongoDB
        conversation_history: Full conversation history
    
    Returns:
        True if saved successfully
    """
    from .mongodb import client, MONGODB_AVAILABLE
    import config
    
    # Add phone number to appointment details
    appointment_details["phone"] = user_phone
    appointment_details["call_sid"] = session_id
    
    # ============ STRICT VALIDATION: CONFIRMED BOOKINGS ONLY ============
    # Only save if ALL required fields are present (not enquiries)
    name = appointment_details.get("name", "") or ""
    doctor = appointment_details.get("doctor", "") or ""
    date_time = appointment_details.get("date_time", "") or ""
    
    # Clean up date_time - remove "None" values
    date_time_clean = date_time.strip().replace("None", "").strip()
    
    has_valid_name = bool(name.strip() and name.strip().lower() != "none")
    has_valid_doctor = bool(doctor.strip() and doctor.strip().lower() != "none")
    has_valid_datetime = bool(date_time_clean and len(date_time_clean) > 2)
    
    # REQUIRE ALL THREE for a confirmed booking
    if not has_valid_name:
        print("⚠️ ENQUIRY ONLY: No patient name - skipping sheet save")
        return False
    
    if not has_valid_doctor:
        print("⚠️ ENQUIRY ONLY: No doctor specified - skipping sheet save")
        return False
    
    if not has_valid_datetime:
        print("⚠️ ENQUIRY ONLY: No date/time specified - skipping sheet save")
        return False
    
    print(f"✅ CONFIRMED BOOKING: Name='{name}', Doctor='{doctor}', DateTime='{date_time_clean}'")
    
    if not MONGODB_AVAILABLE or not client:
        print("⚠️ MongoDB not available, skipping database save")
        # Still try to save to Google Sheets if there's valid data
        save_appointment_to_sheets(appointment_details)
        return False
    
    try:
        db = client[config.MONGODB_DB_NAME]
        appointments_collection = db['appointments']
        
        # Prepare appointment document
        appointment_doc = {
            "session_id": session_id,
            "user_phone": user_phone,
            "patient_name": appointment_details.get("name"),
            "doctor": appointment_details.get("doctor"),
            "preferred_datetime": appointment_details.get("date_time"),
            "phone": user_phone,
            "reason": appointment_details.get("reason"),
            "additional_info": appointment_details.get("additional_info"),
            "status": "pending",
            "created_at": datetime.now(),
            "conversation_summary": str(conversation_history)[:1000]
        }
        
        # Save to MongoDB
        result = appointments_collection.insert_one(appointment_doc)
        print(f"✓ Appointment saved to MongoDB: {result.inserted_id}")
        
        # Save to Google Sheets only if valid booking data exists
        sheets_result = save_appointment_to_sheets(appointment_details)
        print(f"✓ Appointment saved to Google Sheets: {sheets_result}")
        
        return True
        
    except Exception as e:
        print(f"Error saving appointment: {e}")
        return False


def extract_general_queries(conversation_history: List[Dict[str, str]]) -> Dict[str, Any]:
    """
    Extract general queries/concerns from conversation when user doesn't book an appointment.
    This helps understand user behavior and common questions.
    
    Args:
        conversation_history: List of conversation messages
    
    Returns:
        Dictionary with extracted query information
    """
    if not conversation_history:
        return {"queries": "No conversation recorded", "intent": "unknown"}
    
    # Build conversation text for analysis
    user_messages = []
    for msg in conversation_history:
        if msg.get("role") == "user":
            user_messages.append(msg.get("content", ""))
    
    all_queries = " | ".join(user_messages) if user_messages else "No user messages"
    
    # Try to determine intent using LLM
    if config.SARVAM_API_KEY:
        try:
            conversation_text = ""
            for msg in conversation_history:
                role = msg.get("role", "")
                content = msg.get("content", "")
                if role == "user":
                    conversation_text += f"User: {content}\n"
                elif role == "assistant":
                    conversation_text += f"Agent: {content}\n"
            
            extraction_prompt = f"""Analyze this hospital call conversation and extract:
1. Main intent (booking inquiry, general question, complaint, information request, etc.)
2. Key topics/concerns mentioned
3. Why the call ended without booking (if applicable)

Return ONLY a JSON object:
{{
    "intent": "brief description of user's main intent",
    "topics": ["topic1", "topic2"],
    "no_booking_reason": "why user didn't complete booking",
    "summary": "one line summary of the call"
}}

Conversation:
{conversation_text}

Return ONLY valid JSON:"""

            headers = {
                "Content-Type": "application/json",
                "api-subscription-key": config.SARVAM_API_KEY
            }
            
            response = requests.post(
                f"{config.SARVAM_API_URL}/chat/completions",
                json={
                    "model": "sarvam-m",
                    "messages": [{"role": "user", "content": extraction_prompt}],
                    "max_tokens": 200,
                    "temperature": 0.1
                },
                headers=headers,
                timeout=15
            )
            
            if response.status_code == 200:
                result = response.json()
                llm_response = result.get("choices", [{}])[0].get("message", {}).get("content", "")
                
                # Parse JSON response
                import json
                try:
                    # Clean up response
                    llm_response = llm_response.strip()
                    if llm_response.startswith("```"):
                        llm_response = llm_response.split("```")[1]
                        if llm_response.startswith("json"):
                            llm_response = llm_response[4:]
                    
                    extracted = json.loads(llm_response)
                    extracted["raw_queries"] = all_queries
                    return extracted
                except json.JSONDecodeError:
                    pass
                    
        except Exception as e:
            print(f"⚠️ Query extraction error: {e}")
    
    # Fallback: simple extraction
    return {
        "intent": "general inquiry",
        "topics": [],
        "no_booking_reason": "unknown",
        "summary": "Call without completed booking",
        "raw_queries": all_queries
    }


def save_general_query_to_sheets(user_phone: str, query_info: Dict[str, Any], 
                                  session_id: str, conversation_history: List[Dict[str, str]]) -> bool:
    """
    Save general query (non-booking call) to Google Sheets for analytics.
    
    Args:
        user_phone: User's phone number
        query_info: Dictionary with query information
        session_id: Session ID
        conversation_history: Full conversation history
    """
    if not GOOGLE_SHEETS_WEBHOOK_URL:
        print("⚠️ Google Sheets webhook URL not configured")
        return False
    
    try:
        # Prepare data for sheets
        data = {
            "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "Patient Name": "N/A (General Query)",
            "Doctor/Department": "N/A",
            "Preferred Date/Time": "N/A",
            "Phone Number": user_phone,
            "Reason for Visit": query_info.get("summary", "General inquiry"),
            "Additional Info": f"Intent: {query_info.get('intent', 'unknown')} | Topics: {', '.join(query_info.get('topics', []))} | No booking reason: {query_info.get('no_booking_reason', 'N/A')}",
            "Call SID": session_id,
            "Status": "general_query"  # Different status for analytics
        }
        
        # Send to Google Sheets webhook
        response = requests.post(
            GOOGLE_SHEETS_WEBHOOK_URL,
            json=data,
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        
        if response.status_code == 200:
            print(f"✅ General query saved to Google Sheets")
            return True
        else:
            print(f"⚠️ Failed to save general query to sheets: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ Error saving general query to sheets: {e}")
        return False


# Instructions for Google Sheets setup
GOOGLE_SHEETS_SETUP_INSTRUCTIONS = """
=== Google Sheets Integration Setup ===

Option 1: Google Apps Script Webhook
1. Create a new Google Sheet with columns: Timestamp, Patient Name, Doctor/Department, 
   Preferred Date/Time, Phone Number, Reason for Visit, Additional Info, Call SID, Status

2. Go to Extensions > Apps Script

3. Paste this code:

function doPost(e) {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  var data = JSON.parse(e.postData.contents);
  
  sheet.appendRow([
    data["Timestamp"],
    data["Patient Name"],
    data["Doctor/Department"],
    data["Preferred Date/Time"],
    data["Phone Number"],
    data["Reason for Visit"],
    data["Additional Info"],
    data["Call SID"],
    data["Status"]
  ]);
  
  return ContentService.createTextOutput(JSON.stringify({result: "success"}))
    .setMimeType(ContentService.MimeType.JSON);
}

4. Deploy as Web App (Execute as: Me, Access: Anyone)
5. Copy the web app URL
6. Add to .env: GOOGLE_SHEETS_WEBHOOK_URL=your_webapp_url

Option 2: Use Zapier or Make.com
1. Create a Zap/Scenario with webhook trigger
2. Add Google Sheets action
3. Use the webhook URL in .env

"""

if __name__ == "__main__":
    print(GOOGLE_SHEETS_SETUP_INSTRUCTIONS)
