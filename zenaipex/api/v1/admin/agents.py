from fastapi import APIRouter, HTTPException, Depends
from core.database import col_agents, col_companies, col_knowledge_bases
from bson import ObjectId
from pydantic import BaseModel, Field
from typing import Optional

router = APIRouter(prefix="/agents")

class AdminVoiceUpdateRequest(BaseModel):
    tts_voice: str

class AdminVoicePreviewRequest(BaseModel):
    voice: str
    text: Optional[str] = None
    language: Optional[str] = "en-IN"

def _fmt_agent(doc: dict, company_name: str = "Unknown Company") -> dict:
    return {
        "id": str(doc["_id"]),
        "company_id": str(doc.get("company_id", "")),
        "company_name": company_name,
        "name": doc.get("name", "Untitled Agent"),
        "description": doc.get("description", ""),
        "tts_voice": doc.get("tts_voice") or "ritu",
        "default_language": doc.get("default_language", "en-IN"),
        "status": doc.get("status", "draft"),
        "knowledge_base_id": doc.get("knowledge_base_id"),
        "llm_model": doc.get("llm_model", "sarvam-105b"),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }

@router.get("")
async def list_agents():
    """List all agents across all companies with company details."""
    comp_cursor = col_companies().find({})
    comp_map = {}
    async for c in comp_cursor:
        comp_map[str(c["_id"])] = c.get("name", "Unknown Company")

    cursor = col_agents().find({}).sort("created_at", -1)
    agents = []
    async for doc in cursor:
        c_id = str(doc.get("company_id", ""))
        c_name = comp_map.get(c_id, "Unknown Company")
        agents.append(_fmt_agent(doc, c_name))
    return {"agents": agents}

@router.patch("/{agent_id}/voice")
async def admin_update_agent_voice(agent_id: str, body: AdminVoiceUpdateRequest):
    """Platform admin directly updates any agent's TTS voice persona."""
    try:
        oid = ObjectId(agent_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid agent_id")

    res = await col_agents().update_one(
        {"_id": oid},
        {"$set": {"tts_voice": body.tts_voice.lower()}}
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"status": "success", "agent_id": agent_id, "tts_voice": body.tts_voice.lower()}

@router.post("/preview-voice")
async def admin_preview_voice(body: AdminVoicePreviewRequest):
    """Platform admin voice preview synthesis."""
    import base64
    import logging
    from modules.sarvam_tts import realtime_tts

    voice_id = body.voice.lower()
    text = body.text or f"Namaste! Main {voice_id.capitalize()} hoon. Yeh aapka voice sample hai."
    lang = body.language or "en-IN"

    try:
        audio_bytes = await realtime_tts(
            text=text,
            language=lang,
            speaker=voice_id
        )
        if audio_bytes and len(audio_bytes) > 200:
            audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
            return {"audio_base64": audio_b64, "fallback_tts": False, "voice": voice_id}
        else:
            return {"audio_base64": "", "fallback_tts": True, "voice": voice_id}
    except Exception as e:
        logging.warning(f"[ADMIN_VOICE_PREVIEW] Error: {e}")
        return {"audio_base64": "", "fallback_tts": True, "voice": voice_id}

class AdminAgentUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    tts_voice: Optional[str] = None
    llm_model: Optional[str] = None
    status: Optional[str] = None
    default_language: Optional[str] = None

@router.patch("/{agent_id}")
async def admin_update_agent(agent_id: str, body: AdminAgentUpdateRequest):
    """Platform admin updates agent configurations."""
    try:
        oid = ObjectId(agent_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid agent_id")

    update_dict = {k: v for k, v in body.dict(exclude_unset=True).items() if v is not None}
    if not update_dict:
        return {"status": "no_change"}

    from datetime import datetime, timezone
    update_dict["updated_at"] = datetime.now(timezone.utc)
    if "tts_voice" in update_dict:
        update_dict["tts_voice"] = update_dict["tts_voice"].lower()

    res = await col_agents().update_one({"_id": oid}, {"$set": update_dict})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"status": "success", "agent_id": agent_id, "updated": update_dict}

