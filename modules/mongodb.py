"""
MongoDB Module
Handles all database operations for users, sessions, transcripts, and analytics.
Provides session management, conversation history, and risk detection tracking.
"""
from pymongo import MongoClient, ASCENDING, DESCENDING
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from bson.objectid import ObjectId
import time
import config

# Initialize MongoDB client and database with retry logic
MONGODB_AVAILABLE = False
client = None
db = None

def connect_mongodb(max_retries: int = 3, retry_delay: float = 2.0) -> bool:
    """
    Connect to MongoDB with retry logic.
    Returns True if connected successfully.
    """
    global client, db, MONGODB_AVAILABLE
    
    if not config.MONGODB_URI:
        print("⚠️ MONGODB_URI not configured")
        return False
    
    for attempt in range(1, max_retries + 1):
        try:
            if attempt > 1:
                print(f"🔄 MongoDB connection retry {attempt}/{max_retries}...")
            else:
                print("🔌 Connecting to MongoDB...")
            
            client = MongoClient(
                config.MONGODB_URI,
                serverSelectionTimeoutMS=15000,  # Increased timeout
                connectTimeoutMS=15000,
                socketTimeoutMS=20000,
                retryWrites=True,
                w='majority'
            )
            
            # Test connection
            client.admin.command('ping')
            db = client[config.MONGODB_DB_NAME]
            MONGODB_AVAILABLE = True
            print(f"✅ MongoDB connected successfully to database: {config.MONGODB_DB_NAME}")
            return True
            
        except Exception as e:
            print(f"⚠️ MongoDB connection attempt {attempt} failed: {e}")
            if attempt < max_retries:
                time.sleep(retry_delay)
    
    print("⚠️ MongoDB connection failed after all retries")
    print("⚠️ App will continue without MongoDB (using Google Sheets only)")
    client = None
    db = None
    MONGODB_AVAILABLE = False
    return False

# Try initial connection
connect_mongodb()

# Collection Definitions (will be None if not connected)
users_collection = db.users if MONGODB_AVAILABLE else None
sessions_collection = db.sessions if MONGODB_AVAILABLE else None
transcripts_collection = db.transcripts if MONGODB_AVAILABLE else None
therapy_progress_collection = db.therapy_progress if MONGODB_AVAILABLE else None
appointments_collection = db.appointments if MONGODB_AVAILABLE else None
chat_history_collection = db.chat_history if MONGODB_AVAILABLE else None
scheduled_calls_collection = db.scheduled_calls if MONGODB_AVAILABLE else None


def reconnect_mongodb() -> bool:
    """
    Attempt to reconnect to MongoDB and reinitialize collections.
    Useful for recovering from connection loss.
    """
    global users_collection, sessions_collection, transcripts_collection
    global therapy_progress_collection, appointments_collection, chat_history_collection
    global scheduled_calls_collection
    
    if connect_mongodb():
        users_collection = db.users
        sessions_collection = db.sessions
        transcripts_collection = db.transcripts
        therapy_progress_collection = db.therapy_progress
        appointments_collection = db.appointments
        chat_history_collection = db.chat_history
        scheduled_calls_collection = db.scheduled_calls
        return True
    return False


def init_mongodb():
    """
    Initialize MongoDB collections and create indexes for optimal performance.
    Should be called on application startup.
    """
    if not MONGODB_AVAILABLE:
        print("⚠️ MongoDB not available - skipping index creation")
        return
        
    try:
        # User indexes
        users_collection.create_index([("phone", ASCENDING)], unique=True)
        users_collection.create_index([("email", ASCENDING)], sparse=True)
        users_collection.create_index([("created_at", DESCENDING)])
        
        # Session indexes
        sessions_collection.create_index([("user_id", ASCENDING)])
        sessions_collection.create_index([("phone", ASCENDING)])
        sessions_collection.create_index([("session_start", DESCENDING)])
        sessions_collection.create_index([("status", ASCENDING)])
        sessions_collection.create_index([("call_sid", ASCENDING)], sparse=True)
        
        # Transcript indexes
        transcripts_collection.create_index([("session_id", ASCENDING)])
        transcripts_collection.create_index([("user_id", ASCENDING)])
        transcripts_collection.create_index([("timestamp", DESCENDING)])
        transcripts_collection.create_index([("risk_flag", ASCENDING)])
        
        # Chat history indexes
        chat_history_collection.create_index([("user_id", ASCENDING)], unique=True)
        
        # Scheduled calls indexes
        scheduled_calls_collection.create_index([("status", ASCENDING)])
        scheduled_calls_collection.create_index([("scheduled_at", ASCENDING)])
        scheduled_calls_collection.create_index([("next_retry_at", ASCENDING)], sparse=True)
        scheduled_calls_collection.create_index([("phone_number", ASCENDING)])
        scheduled_calls_collection.create_index([("appointment_id", ASCENDING)], sparse=True)
        
        print("MongoDB indexes created successfully")
        return True
        
    except Exception as e:
        print(f"Error initializing MongoDB: {e}")
        return False


# ==================== User Operations ====================

def add_user(user_data: Dict[str, Any]) -> Optional[str]:
    """
    Create a new user.
    
    Args:
        user_data: User information (phone, name, email, etc.)
    
    Returns:
        User ID (string) or None on error
    """
    if not MONGODB_AVAILABLE:
        return None
        
    try:
        user_data['created_at'] = datetime.utcnow()
        user_data['has_interacted_before'] = False
        result = users_collection.insert_one(user_data)
        return str(result.inserted_id)
    except Exception as e:
        print(f"Error adding user: {e}")
        return None


def get_user(user_id: str) -> Optional[Dict[str, Any]]:
    """Get user by ID."""
    try:
        return users_collection.find_one({"_id": ObjectId(user_id)})
    except Exception as e:
        print(f"Error getting user: {e}")
        return None


def get_user_by_phone(phone: str) -> Optional[Dict[str, Any]]:
    """Get user by phone number."""
    try:
        return users_collection.find_one({"phone": phone})
    except Exception as e:
        print(f"Error getting user by phone: {e}")
        return None


def update_user(user_id: str, update_data: Dict[str, Any]) -> bool:
    """Update user information."""
    try:
        update_data['updated_at'] = datetime.utcnow()
        users_collection.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": update_data}
        )
        return True
    except Exception as e:
        print(f"Error updating user: {e}")
        return False


def get_userid_by_phone(phone: str) -> Optional[str]:
    """Get user ID by phone number."""
    try:
        user = users_collection.find_one({"phone": phone})
        return str(user['_id']) if user else None
    except Exception as e:
        print(f"Error getting user ID: {e}")
        return None


def verify_user(phone: str) -> bool:
    """Check if user exists."""
    return users_collection.find_one({"phone": phone}) is not None


def has_interacted_before(phone: str) -> bool:
    """Check if user has interacted before."""
    try:
        user = users_collection.find_one({"phone": phone})
        if user:
            return user.get('has_interacted_before', False)
        return False
    except Exception as e:
        print(f"Error checking interaction: {e}")
        return False


def set_interacted_before(phone: str) -> bool:
    """Mark user as having interacted."""
    try:
        users_collection.update_one(
            {"phone": phone},
            {"$set": {"has_interacted_before": True, "last_interaction": datetime.utcnow()}}
        )
        return True
    except Exception as e:
        print(f"Error setting interaction: {e}")
        return False


# ==================== Session Operations ====================

def create_session(
    user_id: str,
    phone: str,
    call_sid: Optional[str] = None,
    session_type: str = "inbound"
) -> Optional[str]:
    """
    Create a new call session.
    
    Args:
        user_id: User ID
        phone: User phone number
        call_sid: Twilio call SID
        session_type: 'inbound' or 'outbound'
    
    Returns:
        Session ID (string) or None on error
    """
    try:
        session_data = {
            "user_id": user_id,
            "phone": phone,
            "call_sid": call_sid,
            "session_type": session_type,
            "session_start": datetime.utcnow(),
            "session_end": None,
            "status": "active",
            "message_count": 0,
            "duration_seconds": 0,
            "risk_detected": False,
            "metadata": {}
        }
        result = sessions_collection.insert_one(session_data)
        return str(result.inserted_id)
    except Exception as e:
        print(f"Error creating session: {e}")
        return None


def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    """Get session by ID."""
    try:
        return sessions_collection.find_one({"_id": ObjectId(session_id)})
    except Exception as e:
        print(f"Error getting session: {e}")
        return None


def get_active_session(user_id: str) -> Optional[Dict[str, Any]]:
    """Get user's active session if one exists."""
    try:
        return sessions_collection.find_one(
            {"user_id": user_id, "status": "active"},
            sort=[("session_start", DESCENDING)]
        )
    except Exception as e:
        print(f"Error getting active session: {e}")
        return None


def end_session(session_id: str) -> bool:
    """End a session and calculate duration."""
    try:
        session = get_session(session_id)
        if not session:
            return False
        
        end_time = datetime.utcnow()
        duration = (end_time - session['session_start']).total_seconds()
        
        sessions_collection.update_one(
            {"_id": ObjectId(session_id)},
            {
                "$set": {
                    "session_end": end_time,
                    "status": "completed",
                    "duration_seconds": duration
                }
            }
        )
        return True
    except Exception as e:
        print(f"Error ending session: {e}")
        return False


def update_session(session_id: str, update_data: Dict[str, Any]) -> bool:
    """Update session information."""
    try:
        sessions_collection.update_one(
            {"_id": ObjectId(session_id)},
            {"$set": update_data}
        )
        return True
    except Exception as e:
        print(f"Error updating session: {e}")
        return False


def get_user_sessions(
    user_id: str,
    limit: int = 10,
    skip: int = 0
) -> List[Dict[str, Any]]:
    """Get user's session history."""
    try:
        return list(
            sessions_collection.find({"user_id": user_id})
            .sort("session_start", DESCENDING)
            .skip(skip)
            .limit(limit)
        )
    except Exception as e:
        print(f"Error getting user sessions: {e}")
        return []


# ==================== Transcript Operations ====================

def add_transcript(
    session_id: str,
    user_id: str,
    role: str,
    message: str,
    risk_flag: bool = False,
    metadata: Optional[Dict[str, Any]] = None
) -> Optional[str]:
    """
    Add a transcript entry for a conversation turn.
    
    Args:
        session_id: Session ID
        user_id: User ID
        role: 'user' or 'assistant'
        message: Message content
        risk_flag: Whether this message was flagged for crisis/risk
        metadata: Additional metadata (sentiment, retrieval docs, etc.)
    
    Returns:
        Transcript ID (string) or None on error
    """
    try:
        transcript_data = {
            "session_id": session_id,
            "user_id": user_id,
            "role": role,
            "message": message,
            "timestamp": datetime.utcnow(),
            "risk_flag": risk_flag,
            "metadata": metadata or {}
        }
        result = transcripts_collection.insert_one(transcript_data)
        
        # Update session message count
        sessions_collection.update_one(
            {"_id": ObjectId(session_id)},
            {"$inc": {"message_count": 1}}
        )
        
        # Flag session if risk detected
        if risk_flag:
            sessions_collection.update_one(
                {"_id": ObjectId(session_id)},
                {"$set": {"risk_detected": True}}
            )
        
        return str(result.inserted_id)
    except Exception as e:
        print(f"Error adding transcript: {e}")
        return None


def get_session_transcripts(session_id: str) -> List[Dict[str, Any]]:
    """Get all transcripts for a session."""
    try:
        return list(
            transcripts_collection.find({"session_id": session_id})
            .sort("timestamp", ASCENDING)
        )
    except Exception as e:
        print(f"Error getting session transcripts: {e}")
        return []


def get_recent_transcripts(
    user_id: str,
    limit: int = 20
) -> List[Dict[str, Any]]:
    """Get recent transcripts for a user across all sessions."""
    try:
        return list(
            transcripts_collection.find({"user_id": user_id})
            .sort("timestamp", DESCENDING)
            .limit(limit)
        )
    except Exception as e:
        print(f"Error getting recent transcripts: {e}")
        return []


def get_flagged_transcripts(days: int = 7) -> List[Dict[str, Any]]:
    """Get all risk-flagged transcripts from recent days."""
    try:
        cutoff = datetime.utcnow() - timedelta(days=days)
        return list(
            transcripts_collection.find({
                "risk_flag": True,
                "timestamp": {"$gte": cutoff}
            })
            .sort("timestamp", DESCENDING)
        )
    except Exception as e:
        print(f"Error getting flagged transcripts: {e}")
        return []


# ==================== Session Log Operations (Legacy) ====================

def add_session_log(session_data: Dict[str, Any]) -> Optional[str]:
    """Legacy function - use create_session() instead."""
    return create_session(
        user_id=session_data.get('user_id'),
        phone=session_data.get('phone', ''),
        call_sid=session_data.get('call_sid')
    )


def get_session_logs(user_id: str) -> List[Dict[str, Any]]:
    """Legacy function - use get_user_sessions() instead."""
    return get_user_sessions(user_id)

# Therapy progress operations
def add_therapy_progress(progress_data):
    return therapy_progress_collection.insert_one(progress_data).inserted_id

def get_therapy_progress(user_id):
    return list(therapy_progress_collection.find({"user_id": user_id}))

def update_therapy_progress(progress_id, update_data):
    therapy_progress_collection.update_one({"_id": progress_id}, {"$set": update_data})

# Appointment operations
def book_appointment(userid,appointment_data):
    return appointments_collection.insert_one({"user_id":userid},{"appointment_data":appointment_data})

def get_appointments(user_id):
    return list(appointments_collection.find({"user_id": user_id}))

def update_appointment(appointment_id, update_data):
    appointments_collection.update_one({"_id": appointment_id}, {"$set": update_data})

def delete_appointment(appointment_id):
    appointments_collection.delete_one({"_id": appointment_id})

# Chat history operations
def set_chat_history(user_id, message_data):
    """
    Creates a new chat history record or updates an existing one for a user.
    """
    chat_history_collection.update_one(
        {"user_id": user_id},
        {"$push": {"messages": {"$each": message_data}}},  # Using $each to add all elements
        upsert=True
    )

def get_chat_history(user_id):
    """
    Retrieves the chat history for a specific user.
    """
    return chat_history_collection.find_one({"user_id": user_id})

def update_chat_history(user_id, update_data):
    """
    Updates the chat history record for a specific user.
    """
    chat_history_collection.update_one(
        {"user_id": user_id},
        {"$set": update_data}
    )


# ==================== Performance Timing Operations ====================

# Create timing metrics collection
timing_metrics_collection = db.timing_metrics if MONGODB_AVAILABLE else None

def save_timing_metrics(
    call_sid: str,
    session_id: Optional[str],
    turn_number: int,
    metrics: Dict[str, float]
) -> bool:
    """
    Save performance timing metrics for a conversation turn.
    
    Args:
        call_sid: Twilio call SID
        session_id: MongoDB session ID
        turn_number: Turn number in the conversation
        metrics: Dictionary containing timing measurements:
            - download_time: Audio download time in seconds
            - stt_time: Total STT processing time
            - stt_api_time: STT API call time
            - llm_time: Total LLM processing time
            - llm_api_time: LLM API call time
            - tts_time: Total TTS processing time
            - tts_api_time: TTS API call time
            - total_compute_time: Total turn processing time
    
    Returns:
        True if saved successfully, False otherwise
    """
    if not MONGODB_AVAILABLE:
        print("⚠️ MongoDB not available - timing metrics not saved")
        return False
    
    try:
        timing_data = {
            "call_sid": call_sid,
            "session_id": session_id,
            "turn_number": turn_number,
            "timestamp": datetime.utcnow(),
            "metrics": {
                "download_time_ms": metrics.get('download_time', 0) * 1000,
                "stt_time_ms": metrics.get('stt_time', 0) * 1000,
                "stt_api_time_ms": metrics.get('stt_api_time', 0) * 1000,
                "llm_time_ms": metrics.get('llm_time', 0) * 1000,
                "llm_api_time_ms": metrics.get('llm_api_time', 0) * 1000,
                "tts_time_ms": metrics.get('tts_time', 0) * 1000,
                "tts_api_time_ms": metrics.get('tts_api_time', 0) * 1000,
                "total_compute_time_ms": metrics.get('total_compute_time', 0) * 1000,
                "network_time_ms": (
                    metrics.get('stt_api_time', 0) + 
                    metrics.get('llm_api_time', 0) + 
                    metrics.get('tts_api_time', 0)
                ) * 1000
            }
        }
        
        timing_metrics_collection.insert_one(timing_data)
        print(f"✅ Timing metrics saved for turn {turn_number}")
        return True
        
    except Exception as e:
        print(f"❌ Error saving timing metrics: {e}")
        return False


def get_timing_metrics(
    call_sid: Optional[str] = None,
    session_id: Optional[str] = None,
    limit: int = 100
) -> List[Dict[str, Any]]:
    """
    Retrieve timing metrics, optionally filtered by call or session.
    
    Args:
        call_sid: Filter by Twilio call SID
        session_id: Filter by MongoDB session ID
        limit: Maximum number of records to return
    
    Returns:
        List of timing metric records
    """
    if not MONGODB_AVAILABLE:
        return []
    
    try:
        query = {}
        if call_sid:
            query["call_sid"] = call_sid
        if session_id:
            query["session_id"] = session_id
        
        return list(
            timing_metrics_collection
            .find(query)
            .sort("timestamp", DESCENDING)
            .limit(limit)
        )
    except Exception as e:
        print(f"❌ Error retrieving timing metrics: {e}")
        return []


def get_average_timing_metrics(days: int = 7) -> Dict[str, float]:
    """
    Get average timing metrics over a specified period.
    
    Args:
        days: Number of days to look back
    
    Returns:
        Dictionary with average values for each metric
    """
    if not MONGODB_AVAILABLE:
        return {}
    
    try:
        start_date = datetime.utcnow() - timedelta(days=days)
        
        pipeline = [
            {"$match": {"timestamp": {"$gte": start_date}}},
            {"$group": {
                "_id": None,
                "avg_download_time": {"$avg": "$metrics.download_time_ms"},
                "avg_stt_time": {"$avg": "$metrics.stt_time_ms"},
                "avg_stt_api_time": {"$avg": "$metrics.stt_api_time_ms"},
                "avg_llm_time": {"$avg": "$metrics.llm_time_ms"},
                "avg_llm_api_time": {"$avg": "$metrics.llm_api_time_ms"},
                "avg_tts_time": {"$avg": "$metrics.tts_time_ms"},
                "avg_tts_api_time": {"$avg": "$metrics.tts_api_time_ms"},
                "avg_total_compute": {"$avg": "$metrics.total_compute_time_ms"},
                "avg_network_time": {"$avg": "$metrics.network_time_ms"},
                "total_turns": {"$sum": 1}
            }}
        ]
        
        result = list(timing_metrics_collection.aggregate(pipeline))
        if result:
            return result[0]
        return {}
        
    except Exception as e:
        print(f"❌ Error calculating average timing metrics: {e}")
        return {}


# ==================== Scheduled Calls Operations ====================

def create_scheduled_call(call_data: Dict[str, Any]) -> Optional[str]:
    """
    Create a new scheduled call in MongoDB.
    
    Args:
        call_data: Dictionary with phone_number, scheduled_at, timezone, etc.
    
    Returns:
        Schedule ID (string) or None on error
    """
    if not MONGODB_AVAILABLE:
        print("⚠️ MongoDB not available - cannot persist scheduled call")
        return None
    
    try:
        doc = {
            "phone_number": call_data.get("phone_number"),
            "scheduled_at": call_data.get("scheduled_at"),  # datetime in UTC
            "timezone": call_data.get("timezone", "Asia/Kolkata"),
            "status": "scheduled",  # scheduled | in-progress | retrying | completed | failed | cancelled
            "retry_count": 0,
            "max_retries": call_data.get("max_retries", 3),
            "next_retry_at": None,
            "call_sid": None,
            "appointment_id": call_data.get("appointment_id"),  # Link to appointment if reminder
            "call_type": call_data.get("call_type", "manual"),  # manual | reminder
            "reminder_message": call_data.get("reminder_message"),
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "error_message": None
        }
        
        result = scheduled_calls_collection.insert_one(doc)
        schedule_id = str(result.inserted_id)
        print(f"✅ Scheduled call created: {schedule_id}")
        return schedule_id
        
    except Exception as e:
        print(f"❌ Error creating scheduled call: {e}")
        return None


def get_scheduled_call(schedule_id: str) -> Optional[Dict[str, Any]]:
    """Get a scheduled call by ID."""
    if not MONGODB_AVAILABLE:
        return None
    
    try:
        doc = scheduled_calls_collection.find_one({"_id": ObjectId(schedule_id)})
        if doc:
            doc["id"] = str(doc.pop("_id"))
        return doc
    except Exception as e:
        print(f"❌ Error getting scheduled call: {e}")
        return None


def get_pending_scheduled_calls() -> List[Dict[str, Any]]:
    """
    Get all scheduled calls that are due for execution.
    Returns calls where:
    - status='scheduled' AND scheduled_at <= now
    - status='retrying' AND next_retry_at <= now
    """
    if not MONGODB_AVAILABLE:
        return []
    
    try:
        now = datetime.utcnow()
        
        query = {
            "$or": [
                {"status": "scheduled", "scheduled_at": {"$lte": now}},
                {"status": "retrying", "next_retry_at": {"$lte": now}}
            ]
        }
        
        calls = list(scheduled_calls_collection.find(query))
        
        # Convert ObjectId to string
        for call in calls:
            call["id"] = str(call.pop("_id"))
        
        return calls
        
    except Exception as e:
        print(f"❌ Error getting pending scheduled calls: {e}")
        return []


def get_all_scheduled_calls(include_completed: bool = False) -> List[Dict[str, Any]]:
    """Get all scheduled calls, optionally including completed/failed ones."""
    if not MONGODB_AVAILABLE:
        return []
    
    try:
        query = {}
        if not include_completed:
            query["status"] = {"$nin": ["completed", "failed", "cancelled"]}
        
        calls = list(scheduled_calls_collection.find(query).sort("scheduled_at", ASCENDING))
        
        for call in calls:
            call["id"] = str(call.pop("_id"))
        
        return calls
        
    except Exception as e:
        print(f"❌ Error getting scheduled calls: {e}")
        return []


def update_scheduled_call(schedule_id: str, updates: Dict[str, Any]) -> bool:
    """
    Update a scheduled call.
    
    Args:
        schedule_id: The schedule ID
        updates: Dictionary of fields to update
    
    Returns:
        True if successful
    """
    if not MONGODB_AVAILABLE:
        return False
    
    try:
        updates["updated_at"] = datetime.utcnow()
        
        result = scheduled_calls_collection.update_one(
            {"_id": ObjectId(schedule_id)},
            {"$set": updates}
        )
        
        return result.modified_count > 0
        
    except Exception as e:
        print(f"❌ Error updating scheduled call: {e}")
        return False


def cancel_scheduled_call(schedule_id: str) -> bool:
    """Cancel a scheduled call."""
    return update_scheduled_call(schedule_id, {"status": "cancelled"})


def delete_old_scheduled_calls(days: int = 30) -> int:
    """
    Delete completed/failed/cancelled scheduled calls older than specified days.
    
    Returns:
        Number of deleted documents
    """
    if not MONGODB_AVAILABLE:
        return 0
    
    try:
        cutoff = datetime.utcnow() - timedelta(days=days)
        
        result = scheduled_calls_collection.delete_many({
            "status": {"$in": ["completed", "failed", "cancelled"]},
            "updated_at": {"$lt": cutoff}
        })
        
        if result.deleted_count > 0:
            print(f"🧹 Cleaned up {result.deleted_count} old scheduled calls")
        
        return result.deleted_count
        
    except Exception as e:
        print(f"❌ Error deleting old scheduled calls: {e}")
        return 0


def get_upcoming_appointments(hours_ahead: int = 24) -> List[Dict[str, Any]]:
    """
    Get appointments scheduled within the next N hours that don't have reminder calls scheduled.
    Used for auto-scheduling reminder calls.
    
    Args:
        hours_ahead: Look ahead window in hours
    
    Returns:
        List of appointments needing reminders
    """
    if not MONGODB_AVAILABLE:
        return []
    
    try:
        now = datetime.utcnow()
        future = now + timedelta(hours=hours_ahead)
        
        # Get appointments in the time window
        # Note: preferred_datetime might be stored as string, so we need to handle both
        appointments = list(appointments_collection.find({
            "status": {"$in": ["pending", "confirmed"]},
            "reminder_scheduled": {"$ne": True}
        }))
        
        upcoming = []
        for apt in appointments:
            # Try to parse the datetime
            dt_str = apt.get("preferred_datetime", "")
            if not dt_str:
                continue
            
            try:
                # Handle various date formats
                if isinstance(dt_str, datetime):
                    apt_dt = dt_str
                elif isinstance(dt_str, str):
                    # Try parsing common formats
                    for fmt in ["%Y-%m-%d %I:%M %p", "%Y-%m-%d %H:%M", "%d/%m/%Y %I:%M %p", "%d-%m-%Y %I:%M %p"]:
                        try:
                            apt_dt = datetime.strptime(dt_str.strip(), fmt)
                            break
                        except:
                            continue
                    else:
                        continue
                else:
                    continue
                
                # Check if within window
                if now <= apt_dt <= future:
                    apt["id"] = str(apt.pop("_id"))
                    upcoming.append(apt)
                    
            except Exception as parse_error:
                continue
        
        return upcoming
        
    except Exception as e:
        print(f"❌ Error getting upcoming appointments: {e}")
        return []


def mark_appointment_reminder_scheduled(appointment_id: str) -> bool:
    """Mark an appointment as having a reminder scheduled."""
    if not MONGODB_AVAILABLE:
        return False
    
    try:
        result = appointments_collection.update_one(
            {"_id": ObjectId(appointment_id)},
            {"$set": {"reminder_scheduled": True, "reminder_scheduled_at": datetime.utcnow()}}
        )
        return result.modified_count > 0
    except Exception as e:
        print(f"❌ Error marking appointment reminder: {e}")
        return False