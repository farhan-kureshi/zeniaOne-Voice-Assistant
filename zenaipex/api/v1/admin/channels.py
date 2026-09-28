"""
Admin Channels API.
"""
from fastapi import APIRouter, Query
from typing import Optional
from pydantic import BaseModel
from twilio.rest import Client
import logging

logger = logging.getLogger(__name__)
from core.config import settings
from services import channel_service
from core.database import col_channels, col_conversations, col_messages
from core.exceptions import NotFoundError
from bson import ObjectId

router = APIRouter()

@router.get("/channels", summary="List all channels across platform")
async def list_all_channels(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, le=500),
):
    channels = await channel_service.list_all_channels_admin(skip=skip, limit=limit)
    
    def _fmt(doc):
        return {
            "id": str(doc["_id"]),
            "company_id": doc["company_id"],
            "agent_id": doc["agent_id"],
            "name": doc["name"],
            "type": doc["type"],
            "phone_number": doc.get("phone_number"),
            "public_identifier": doc.get("public_identifier"),
            "is_active": doc.get("is_active", True),
            "created_at": doc.get("created_at"),
            "updated_at": doc.get("updated_at"),
        }
        
    return {"channels": [_fmt(c) for c in channels], "count": len(channels)}

@router.get("/channels/{channel_id}", summary="Get channel details as admin")
async def get_channel_admin(channel_id: str):
    channel = await col_channels().find_one({"_id": ObjectId(channel_id)})
    if not channel:
        raise NotFoundError("Channel")
    # Get all Twilio voice channels for this company to determine phone number pool
    company_voice_channels = await col_channels().find({
        "company_id": channel["company_id"],
        "type": "twilio_voice",
        "is_active": True
    }).to_list(length=100)
    
    company_numbers = [c.get("phone_number") for c in company_voice_channels if c.get("phone_number")]
    
    allowed_domains = channel.get("config", {}).get("allowed_domains", ["Any (Not strict)"])
    if not isinstance(allowed_domains, list):
        allowed_domains = ["Any (Not strict)"]
        
    return {
        "id": str(channel["_id"]),
        "company_id": channel["company_id"],
        "agent_id": channel.get("agent_id"),
        "name": channel["name"],
        "type": channel["type"],
        "phone_number": channel.get("phone_number"),
        "public_identifier": channel.get("public_identifier"),
        "is_active": channel.get("is_active", True),
        "created_at": channel.get("created_at"),
        "updated_at": channel.get("updated_at"),
        "company_numbers": company_numbers,
        "allowed_domains": allowed_domains
    }

@router.get("/channels/{channel_id}/conversations", summary="Get conversations for a channel")
async def get_channel_conversations(channel_id: str, limit: int = 50):
    channel = await col_channels().find_one({"_id": ObjectId(channel_id)})
    if not channel:
        raise NotFoundError("Channel")
    
    query = {}
    if channel.get("type") in ["twilio_voice", "exotel_voice"]:
        or_conditions = [{"channel_id": str(channel["_id"])}]
        if channel.get("phone_number"):
            or_conditions.append({"caller_to": channel["phone_number"]})
            or_conditions.append({"caller_phone": channel["phone_number"]})
        query = {"$or": or_conditions}
    elif channel.get("type") == "web_chat" and channel.get("public_identifier"):
        query = {"caller_to": channel["public_identifier"]}
    else:
        return {"conversations": []}

    cursor = col_conversations().find(query).sort("started_at", -1).limit(limit)
    convs = await cursor.to_list(length=limit)
    
    def _fmt(doc):
        return {
            "id": str(doc["_id"]),
            "company_id": str(doc.get("company_id", "")),
            "caller_phone": doc.get("caller_phone"),
            "caller_to": doc.get("caller_to"),
            "recording_url": doc.get("recording_url"),
            "status": doc.get("status"),
            "created_at": doc.get("started_at") or doc.get("created_at"),
            "duration_seconds": doc.get("duration_seconds", 0),
            "turn_count": doc.get("turn_count", 0),
            "title": doc.get("title", "Voice Call"),
            "direction": doc.get("direction", "inbound")
        }
        
    return {"conversations": [_fmt(c) for c in convs]}

@router.get("/conversations/by-call-sid/{call_sid}", summary="Get live conversation by call SID")
async def get_conversation_by_call_sid(call_sid: str):
    conv = await col_conversations().find_one({"call_sid": call_sid})
    if not conv:
        raise NotFoundError("Conversation")
        
    messages = await col_messages().find({"conversation_id": str(conv["_id"])}).sort("created_at", 1).to_list(None)
    
    return {
        "id": str(conv["_id"]),
        "status": conv.get("status", "in_progress"),
        "recording_url": conv.get("recording_url"),
        "messages": [
            {
                "id": str(m["_id"]),
                "role": m.get("role"),
                "content": m.get("content"),
                "created_at": m.get("created_at")
            } for m in messages
        ]
    }

class TestCallRequest(BaseModel):
    contact_name: str
    phone_number: str
    topic: str
    system_prompt: Optional[str] = None

@router.post("/channels/{channel_id}/test-call", summary="Trigger outbound test call")
async def trigger_test_call(channel_id: str, body: TestCallRequest):
    channel = await col_channels().find_one({"_id": ObjectId(channel_id)})
    if not channel:
        raise NotFoundError("Channel")
    
    # We need a Twilio number to call FROM.
    # Get all Twilio voice channels for this company to determine phone number pool
    company_voice_channels = await col_channels().find({
        "company_id": channel["company_id"],
        "type": "twilio_voice",
        "is_active": True
    }).to_list(length=100)
    
    company_numbers = ["08047285182"] # Hardcoded Exophone
    from_number = company_numbers[0]
    
    try:
        import requests
        from requests.auth import HTTPBasicAuth
        
        exotel_sid = "zeniaone1"
        exotel_key = "e4d53113134e108d71772166cedfdf51455e547530d8d56c"
        exotel_token = "29cdec574842f8160b1585244f6a24b3b3521b880c5cb9ab"
        
        company_id = channel.get("company_id", "")
        agent_id = channel.get("agent_id", "")
        import os
        from dotenv import dotenv_values
        env_dict = dotenv_values(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), ".env"))
        actual_webhook = env_dict.get("PLATFORM_WEBHOOK_BASE_URL", settings.platform_webhook_base_url)
        
        webhook_url = f"{settings.app_base_url.replace('localhost', '127.0.0.1')}/api/v1/webhook/exotel/advanced/{company_id}/{agent_id}/voice"
        if "loca.lt" in actual_webhook or "ngrok" in actual_webhook or "trycloudflare.com" in actual_webhook:
            webhook_url = f"{actual_webhook}/api/v1/webhook/exotel/advanced/{company_id}/{agent_id}/voice"
            
        host = actual_webhook.replace("https://", "").replace("http://", "")
        scheme = "wss" if "localhost" not in host and "127.0.0.1" not in host else "ws"
        ws_url = f"{scheme}://{host}/api/v1/webhook/exotel/advanced/{company_id}/{agent_id}/media-stream"
        
        import urllib.parse
        encoded_name = urllib.parse.quote(body.contact_name)
        channel_id_str = str(channel.get('_id', ''))
        webhook_url += f"?contact_name={encoded_name}&provider=exotel&channel_id={channel_id_str}"
        ws_url += f"?contact_name={encoded_name}&channel_id={channel_id_str}"
        
        dest_number = body.phone_number.replace(" ", "").replace("-", "").strip()
        logger.info(f"Triggering Exotel Call: TO={dest_number} EXOPHONE={from_number} WSS={ws_url}")
        
        # Exotel Connect Voice API (AgentStream)
        url = f"https://api.exotel.com/v1/Accounts/{exotel_sid}/Calls/connect.json"
        
        status_webhook_url = f"{actual_webhook}/api/v1/webhook/exotel/advanced/{company_id}/{agent_id}/status"
        
        payload = {
            "From": dest_number,          # Customer number
            "CallerId": from_number,      # Our Exophone
            "StreamUrl": ws_url,          # Exotel connects directly to Websocket
            "StreamType": "bidirectional",
            "Record": "true",
            "StatusCallback": status_webhook_url,
            "StatusCallbackEvents[0]": "terminal"
        }
        
        response = requests.post(url, data=payload, auth=HTTPBasicAuth(exotel_key, exotel_token))
        if response.status_code in [200, 201]:
            resp_data = response.json()
            call_sid = resp_data.get("Call", {}).get("Sid", "unknown")
            
            # PRE-CREATE CONVERSATION SO IT SHOWS IN DASHBOARD IMMEDIATELY
            from zenaipex.services.conversation_service import create_conversation
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(create_conversation(
                    company_id=company_id,
                    agent_id=agent_id,
                    channel_id=str(channel.get('_id', '')),
                    call_sid=call_sid,
                    caller_phone=dest_number,
                    caller_to=from_number,
                    direction="outbound"
                ))
            except Exception as loop_e:
                logger.error(f"Failed to schedule create_conversation task: {loop_e}")

            return {"success": True, "call_sid": call_sid, "message": f"Dialing {dest_number} from Exotel {from_number}..."}
        else:
            logger.error(f"Exotel Error: {response.text}")
            return {"success": False, "message": f"Exotel Error {response.status_code}: {response.text}"}
            
    except Exception as e:
        logger.error(f"Failed to trigger Exotel call: {e}")
        return {"success": False, "message": str(e)}
