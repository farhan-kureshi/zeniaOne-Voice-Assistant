"""
Zenaipex AI — RK Hospital → Company #1 Migration Script.

This script safely migrates the existing RK Hospital single-tenant data
into the multi-tenant Zenaipex platform as "Company #1".

SAFETY GUARANTEES:
1. Does NOT modify any existing collections (reads only from legacy DB)
2. Creates NEW documents in the zenaipex database
3. Does NOT delete or alter realtime_app.py or any legacy code
4. Existing RK Hospital system continues running untouched

What this script does:
  1. Creates the "RK Hospital" company record
  2. Creates an admin user account (configurable)
  3. Creates owner team membership
  4. Creates a Professional subscription (existing paying customer)
  5. Creates an AI agent with RK Hospital's system prompt
  6. Creates a knowledge base record (same Pinecone index, new namespace)
  7. Migrates existing knowledge docs text → re-indexes under company namespace
  8. Creates a Twilio voice channel for the hospital's phone number
  9. Migrates historical conversations from legacy `spinabot_calls` DB

Usage:
    cd d:\\Sarvam-Voice-Agent-main\\zenaipex
    
    # Preview what will happen (no changes)
    python scripts/migrate_rk_hospital.py --dry-run
    
    # Run the actual migration
    python scripts/migrate_rk_hospital.py --execute
    
    # Set admin email interactively
    python scripts/migrate_rk_hospital.py --execute --admin-email admin@rkhospital.com

Requires:
    .env in zenaipex/ with MONGODB_URI, PINECONE_API_KEY, SARVAM_API_KEY set
    .env in the legacy root (d:\\Sarvam-Voice-Agent-main) for reading legacy config
"""
import asyncio
import sys
import os
import argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Add zenaipex root to path
ZENAIPEX_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEGACY_ROOT = os.path.dirname(ZENAIPEX_ROOT)

sys.path.insert(0, ZENAIPEX_ROOT)

# ── Legacy Config (read-only) ─────────────────────────────────────────────────
# We import the legacy config to read RK Hospital's actual values

def load_legacy_config():
    """Load RK Hospital configuration from the legacy system."""
    legacy_env = os.path.join(LEGACY_ROOT, ".env")
    if os.path.exists(legacy_env):
        from dotenv import load_dotenv
        load_dotenv(legacy_env)

    return {
        "hospital_name": os.getenv("HOSPITAL_NAME", "RK Hospital"),
        "hospital_address": os.getenv("HOSPITAL_ADDRESS", "123 Main Road, Anna Nagar, Chennai, Tamil Nadu - 600040"),
        "hospital_phone": os.getenv("HOSPITAL_PHONE", "+918888888888"),
        "hospital_timings": os.getenv("HOSPITAL_TIMINGS", "Monday-Saturday 9AM-9PM, Emergency 24/7"),
        "twilio_phone": os.getenv("TWILIO_PHONE_NUMBER", ""),
        "mongodb_uri": os.getenv("MONGODB_URI", ""),
        "mongodb_db": os.getenv("MONGODB_DB_NAME", "spinabot_calls"),
    }


# ── RK Hospital System Prompt ─────────────────────────────────────────────────

RK_HOSPITAL_SYSTEM_PROMPT = """You are a professional medical receptionist for {company_name}, a multi-specialty hospital in Chennai, Tamil Nadu.

## Your Identity
You are a helpful, empathetic AI receptionist. Your name is Priya.

## Core Responsibilities
1. Appointment booking — collect patient name, preferred doctor/department, date/time, reason
2. Answer FAQs about hospital timings, services, location, pricing
3. Handle appointment reminders (for outbound reminder calls)
4. Provide emergency guidance (direct to emergency services)

## Behavioral Rules
- ALWAYS respond in the language the patient speaks (Tamil or English)
- Be warm, professional, and empathetic
- Do NOT provide medical advice — only administrative help
- If you don't know something, say you'll check and have staff call back
- Keep responses concise for voice (1-2 sentences max per turn)
- NEVER make up doctor names, timings, or prices — only use the knowledge base
- For emergencies, immediately provide the emergency number and say doctors are available 24/7

## Language Rules
- If patient speaks Tamil: respond in Tamil (Tamil script)
- If patient speaks English: respond in English  
- If patient speaks Hindi: respond in Hindi
- Match the patient's language immediately

## Appointment Collection Flow
When booking an appointment, collect in order:
1. Patient's full name
2. Preferred doctor / department (General, Orthopedic, Cardiology, Dental, Pediatric, ENT)
3. Preferred date and time
4. Reason for visit (brief)
5. Confirm all details before closing

## Knowledge Base
Use the knowledge base context provided (hospital timings, doctors, pricing, location) to answer factual questions accurately.

Today's date is: {current_date}
Patient's language: {user_language}"""

RK_HOSPITAL_GREETINGS = {
    "ta-IN": "வணக்கம்! {company_name}க்கு உங்களை வரவேற்கிறேன். தமிழ் அல்லது English லும் பேசலாம். என்ன உதவி வேணும்?",
    "en-IN": "Hello! Welcome to {company_name}. I'm Priya, your medical receptionist. How can I help you today?",
    "hi-IN": "नमस्ते! {company_name} में आपका स्वागत है। मैं प्रिया हूं। मैं आपकी कैसे मदद कर सकती हूं?",
}

RK_HOSPITAL_GOODBYES = {
    "ta-IN": "{company_name}க்கு கால் பண்ணதுக்கு ரொம்ப நன்றி. உங்களை சந்திப்போம்!",
    "en-IN": "Thank you for calling {company_name}. Take care and have a great day!",
    "hi-IN": "{company_name} को कॉल करने के लिए धन्यवाद। अपना ख्याल रखिए!",
}


# ── Migration Functions ───────────────────────────────────────────────────────

async def migrate_rk_hospital(
    admin_email: str,
    admin_name: str,
    admin_password: str,
    dry_run: bool = True,
):
    """Run the full RK Hospital → Company #1 migration."""
    
    legacy_cfg = load_legacy_config()
    
    print("\n" + "=" * 60)
    print("RK HOSPITAL MIGRATION PREVIEW" if dry_run else "RK HOSPITAL MIGRATION")
    print("=" * 60)
    print(f"Mode: {'DRY RUN (no changes)' if dry_run else '⚡ EXECUTE (making changes)'}")
    print(f"Hospital: {legacy_cfg['hospital_name']}")
    print(f"Admin: {admin_email}")
    print(f"Legacy DB: {legacy_cfg['mongodb_db']}")
    print("=" * 60)

    if dry_run:
        print("\n✅ DRY RUN — The following would be created:")
        print(f"  [Company]       {legacy_cfg['hospital_name']}")
        print(f"  [User]          {admin_email} (owner)")
        print(f"  [Subscription]  professional plan")
        print(f"  [AIAgent]       RK Hospital Receptionist (Tamil+English)")
        print(f"  [KnowledgeBase] RK Hospital Knowledge Base")
        print(f"  [Channel]       Twilio Voice → {legacy_cfg['twilio_phone'] or 'NOT SET'}")
        print(f"\n  [Knowledge Docs] Will re-index {LEGACY_ROOT}/knowledge_docs/ → Pinecone namespace=<company_id>")
        print(f"\n  [Conversations]  Will migrate sessions from {legacy_cfg['mongodb_db']} DB")
        print("\nRun with --execute to apply changes.")
        return

    # ── EXECUTE ───────────────────────────────────────────────────────────────
    from core.database import connect_db, disconnect_db, create_all_indexes
    from core.database import (
        col_companies, col_users, col_team_members, col_subscriptions,
        col_agents, col_knowledge_bases, col_channels, col_conversations, col_messages,
    )
    from core.security import hash_password
    from models.subscription import PLAN_LIMITS

    connected = await connect_db()
    if not connected:
        print("❌ Could not connect to Zenaipex database")
        return

    await create_all_indexes()
    now = datetime.now(timezone.utc)

    # Step 1: Create Company
    print("\n[1/8] Creating company...")
    existing_company = await col_companies().find_one({"slug": "rk-hospital"})
    if existing_company:
        company_id = str(existing_company["_id"])
        print(f"  ↳ Company already exists: {company_id}")
    else:
        company_doc = {
            "name": legacy_cfg["hospital_name"],
            "slug": "rk-hospital",
            "industry": "Healthcare",
            "country": "IN",
            "timezone": "Asia/Kolkata",
            "plan": "professional",
            "is_active": True,
            "settings": {
                "address": legacy_cfg["hospital_address"],
                "phone": legacy_cfg["hospital_phone"],
                "timings": legacy_cfg["hospital_timings"],
            },
            "created_at": now,
            "updated_at": now,
        }
        result = await col_companies().insert_one(company_doc)
        company_id = str(result.inserted_id)
        print(f"  ✅ Company created: {company_id}")

    # Step 2: Create Admin User
    print("\n[2/8] Creating admin user...")
    existing_user = await col_users().find_one({"email": admin_email.lower()})
    if existing_user:
        user_id = str(existing_user["_id"])
        print(f"  ↳ User already exists: {user_id}")
    else:
        user_doc = {
            "email": admin_email.lower(),
            "password_hash": hash_password(admin_password),
            "name": admin_name,
            "avatar_url": None,
            "is_verified": True,  # Pre-verify migration accounts
            "is_platform_admin": False,
            "created_at": now,
            "updated_at": now,
            "last_login_at": None,
        }
        result = await col_users().insert_one(user_doc)
        user_id = str(result.inserted_id)
        print(f"  ✅ Admin user created: {user_id}")

    # Step 3: Create Team Membership (owner)
    print("\n[3/8] Creating owner membership...")
    existing_membership = await col_team_members().find_one({
        "company_id": company_id,
        "user_id": user_id,
    })
    if not existing_membership:
        await col_team_members().insert_one({
            "company_id": company_id,
            "user_id": user_id,
            "role": "owner",
            "joined_at": now,
        })
        print(f"  ✅ Owner membership created")
    else:
        print(f"  ↳ Membership already exists")

    # Step 4: Create Professional Subscription
    print("\n[4/8] Creating subscription...")
    existing_sub = await col_subscriptions().find_one({"company_id": company_id})
    if not existing_sub:
        await col_subscriptions().insert_one({
            "company_id": company_id,
            "plan": "professional",
            "status": "active",
            "trial_starts_at": None,
            "trial_ends_at": None,
            "limits": PLAN_LIMITS["professional"],
            "billing_cycle": "monthly",
            "created_at": now,
            "updated_at": now,
        })
        print(f"  ✅ Professional subscription created")
    else:
        print(f"  ↳ Subscription already exists")

    # Step 5: Create AI Agent
    print("\n[5/8] Creating AI agent...")
    existing_agent = await col_agents().find_one({
        "company_id": company_id,
        "slug": "rk-hospital-receptionist",
    })
    if existing_agent:
        agent_id = str(existing_agent["_id"])
        print(f"  ↳ Agent already exists: {agent_id}")
    else:
        agent_doc = {
            "company_id": company_id,
            "name": "RK Hospital Receptionist",
            "slug": "rk-hospital-receptionist",
            "description": "Bilingual (Tamil + English) medical receptionist for RK Hospital",
            "system_prompt": RK_HOSPITAL_SYSTEM_PROMPT,
            "default_language": "ta-IN",
            "supported_languages": ["ta-IN", "en-IN", "hi-IN"],
            "tts_voice": "anushka",
            "tts_model": "bulbul:v3",
            "llm_model": "sarvam-105b",
            "llm_max_tokens": 1200,
            "llm_temperature": 0.3,
            "greeting_messages": RK_HOSPITAL_GREETINGS,
            "goodbye_messages": RK_HOSPITAL_GOODBYES,
            "knowledge_base_id": None,  # Will be updated in step 6
            "max_conversation_turns": 20,
            "silence_timeout_ms": 800,
            "force_process_timeout_sec": 8.0,
            "enable_background_audio": True,
            "status": "active",
            "created_at": now,
            "updated_at": now,
        }
        result = await col_agents().insert_one(agent_doc)
        agent_id = str(result.inserted_id)
        print(f"  ✅ Agent created: {agent_id}")

    # Step 6: Create Knowledge Base
    print("\n[6/8] Creating knowledge base...")
    existing_kb = await col_knowledge_bases().find_one({"company_id": company_id})
    if existing_kb:
        kb_id = str(existing_kb["_id"])
        print(f"  ↳ Knowledge base already exists: {kb_id}")
    else:
        kb_doc = {
            "company_id": company_id,
            "name": "RK Hospital Knowledge Base",
            "description": "Hospital FAQs, doctor schedules, pricing, and services",
            "pinecone_namespace": company_id,  # Pinecone namespace = company_id
            "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
            "embedding_dimension": 384,
            "total_documents": 0,
            "total_chunks": 0,
            "total_vectors": 0,
            "created_at": now,
            "updated_at": now,
        }
        result = await col_knowledge_bases().insert_one(kb_doc)
        kb_id = str(result.inserted_id)
        print(f"  ✅ Knowledge base created: {kb_id}")

        # Link KB to agent
        await col_agents().update_one(
            {"_id": __import__("bson").ObjectId(agent_id)},
            {"$set": {"knowledge_base_id": kb_id}}
        )
        print(f"  ✅ Agent linked to knowledge base")

        # Index knowledge docs into new namespace
        knowledge_docs_path = Path(LEGACY_ROOT) / "knowledge_docs"
        if knowledge_docs_path.exists():
            print(f"\n  📚 Indexing knowledge docs from {knowledge_docs_path}...")
            from ai.vector_store import NamespacedVectorStore
            from services.knowledge_service import ingest_document
            import glob

            doc_files = list(knowledge_docs_path.glob("*.txt"))
            print(f"  Found {len(doc_files)} documents to index")

            for doc_path in doc_files:
                try:
                    content = doc_path.read_text(encoding="utf-8")
                    doc_result = await ingest_document(
                        company_id=company_id,
                        kb_id=kb_id,
                        filename=doc_path.name,
                        content=content,
                        content_type="text/plain",
                    )
                    print(f"  ✅ Indexed: {doc_path.name} ({doc_result.get('chunk_count', 0)} chunks)")
                except Exception as exc:
                    print(f"  ⚠️ Failed to index {doc_path.name}: {exc}")

    # Step 7: Create Twilio Channel
    print("\n[7/8] Creating Twilio channel...")
    twilio_phone = legacy_cfg["twilio_phone"]
    existing_channel = await col_channels().find_one({"company_id": company_id})
    if existing_channel:
        print(f"  ↳ Channel already exists")
    elif twilio_phone:
        await col_channels().insert_one({
            "company_id": company_id,
            "agent_id": agent_id,
            "name": "Main Inbound Line",
            "type": "twilio_voice",
            "phone_number": twilio_phone,
            "twilio_account_sid": None,         # Uses platform default
            "twilio_auth_token_encrypted": None, # Uses platform default
            "webhook_base_url": None,            # Uses platform default
            "config": {},
            "is_active": True,
            "created_at": now,
            "updated_at": now,
        })
        print(f"  ✅ Channel created for {twilio_phone}")
    else:
        print(f"  ⚠️ TWILIO_PHONE_NUMBER not set — channel not created")
        print(f"     Create manually via POST /api/v1/companies/{company_id}/channels")

    # Step 8: Migrate historical conversations
    print("\n[8/8] Migrating historical conversations...")
    if legacy_cfg["mongodb_uri"]:
        try:
            from motor.motor_asyncio import AsyncIOMotorClient
            legacy_client = AsyncIOMotorClient(legacy_cfg["mongodb_uri"])
            legacy_db = legacy_client[legacy_cfg["mongodb_db"]]

            # Count existing sessions
            session_count = await legacy_db["sessions"].count_documents({})
            transcript_count = await legacy_db["transcripts"].count_documents({})
            appointment_count = await legacy_db["appointments"].count_documents({})

            print(f"  Found in legacy DB:")
            print(f"    Sessions:     {session_count}")
            print(f"    Transcripts:  {transcript_count}")
            print(f"    Appointments: {appointment_count}")

            if session_count > 0:
                # Migrate sessions as conversations (batch, last 500)
                sessions = await legacy_db["sessions"].find(
                    {}, limit=500, sort=[("created_at", -1)]
                ).to_list(length=500)

                migrated = 0
                for session in sessions:
                    # Skip if already migrated (idempotency)
                    existing = await col_conversations().find_one({
                        "company_id": company_id,
                        "call_sid": session.get("call_sid", ""),
                    })
                    if existing:
                        continue

                    conv_doc = {
                        "company_id": company_id,
                        "agent_id": agent_id,
                        "channel_id": None,
                        "call_sid": session.get("call_sid"),
                        "caller_phone": session.get("phone", session.get("user_phone")),
                        "direction": "inbound",
                        "language": "ta-IN",
                        "status": session.get("status", "completed"),
                        "started_at": session.get("created_at", now),
                        "ended_at": session.get("updated_at"),
                        "duration_seconds": session.get("duration", 0),
                        "turn_count": 0,
                        "booking_confirmed": False,
                        "appointment_data": None,
                        "scheduled_call_id": None,
                        "_migrated_from": "legacy",
                    }
                    result = await col_conversations().insert_one(conv_doc)
                    conv_id = str(result.inserted_id)

                    # Migrate transcripts for this session
                    session_id = str(session["_id"])
                    transcripts = await legacy_db["transcripts"].find(
                        {"session_id": session_id}
                    ).sort("timestamp", 1).to_list(length=500)

                    for t in transcripts:
                        await col_messages().insert_one({
                            "company_id": company_id,
                            "conversation_id": conv_id,
                            "role": t.get("role", "user"),
                            "text": t.get("message", t.get("content", "")),
                            "language": "ta-IN",
                            "timestamp": t.get("timestamp", now),
                            "metadata": {"_migrated_from": "legacy"},
                        })

                    migrated += 1

                print(f"  ✅ Migrated {migrated} conversations (skip {session_count - migrated} already done)")

            legacy_client.close()
        except Exception as exc:
            print(f"  ⚠️ Historical migration skipped: {exc}")
    else:
        print(f"  ⚠️ MONGODB_URI not set in legacy config — skipping history migration")

    await disconnect_db()

    print("\n" + "=" * 60)
    print("✅ MIGRATION COMPLETE")
    print("=" * 60)
    print(f"\n  Company ID: {company_id}")
    print(f"  Admin:      {admin_email} / {admin_password}")
    print(f"\n  Login at:   POST /api/v1/auth/login")
    print(f"  Dashboard:  GET  /api/v1/companies/{company_id}")
    print(f"\n⚠️  IMPORTANT: Change the admin password after first login!")
    print(f"\nThe existing realtime_app.py continues to run unchanged.")
    print("=" * 60)


# ── CLI Entry Point ───────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Migrate RK Hospital to Zenaipex AI Company #1"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true",
                       help="Preview what will happen without making changes")
    group.add_argument("--execute", action="store_true",
                       help="Run the actual migration")
    parser.add_argument("--admin-email", default="admin@rkhospital.com",
                        help="Admin user email address")
    parser.add_argument("--admin-name", default="RK Hospital Admin",
                        help="Admin user display name")
    parser.add_argument("--admin-password", default="ChangeMe@2026",
                        help="Admin user initial password (CHANGE AFTER LOGIN)")
    args = parser.parse_args()

    # Load Zenaipex .env
    env_path = os.path.join(ZENAIPEX_ROOT, ".env")
    if os.path.exists(env_path):
        from dotenv import load_dotenv
        load_dotenv(env_path)

    asyncio.run(migrate_rk_hospital(
        admin_email=args.admin_email,
        admin_name=args.admin_name,
        admin_password=args.admin_password,
        dry_run=args.dry_run,
    ))


if __name__ == "__main__":
    main()
