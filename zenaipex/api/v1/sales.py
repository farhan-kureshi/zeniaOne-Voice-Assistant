from fastapi import APIRouter, Depends, Path, HTTPException
from typing import List
from datetime import datetime, timezone
from bson import ObjectId
import logging

from core.dependencies import get_unverified_auth_context, require_admin, AuthContext
from core.database import col_leads, col_sales_calls, col_agents
from models.sales import LeadCreate, LeadResponse, SalesCallCreate, SalesCallResponse, CallStatus, SalesCallSummary
from modules.telephony.mock_provider import MockTelephonyProvider
from pydantic import BaseModel
from services import conversation_service
from ai.llm import AgentLLMClient
from typing import Dict, Any, Optional
import asyncio
from core.database import col_conversations


class WebhookEvent(BaseModel):
    event: str  # ringing, answered, completed, failed, no_answer
    provider_call_id: Optional[str] = None
    reason: Optional[str] = None

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Sales Calls"])
telephony_provider = MockTelephonyProvider()

@router.post("/companies/{company_id}/leads", response_model=LeadResponse, status_code=201)
async def create_lead(
    body: LeadCreate,
    company_id: str = Path(...),
    ctx: AuthContext = Depends(require_admin)
):
    doc = body.model_dump()
    doc["company_id"] = company_id
    doc["status"] = "new"
    now = datetime.now(timezone.utc)
    doc["created_at"] = now
    doc["updated_at"] = now
    
    res = await col_leads().insert_one(doc)
    doc["id"] = str(res.inserted_id)
    return doc

class PublicLeadResponse(BaseModel):
    status: str

@router.post("/companies/{company_id}/leads/public", response_model=PublicLeadResponse, status_code=201)
async def create_public_lead(
    body: LeadCreate,
    company_id: str = Path(...)
):
    doc = body.model_dump()
    doc["company_id"] = company_id
    doc["status"] = "new"
    now = datetime.now(timezone.utc)
    doc["created_at"] = now
    doc["updated_at"] = now
    
    # Optional: basic rate-limiting or IP checking could go here in future
    
    await col_leads().insert_one(doc)
    
    # We do NOT return the lead details or ID to public users
    return {"status": "success"}

@router.get("/companies/{company_id}/leads", response_model=List[LeadResponse])
async def list_leads(
    company_id: str = Path(...),
    ctx: AuthContext = Depends(require_admin)
):
    cursor = col_leads().find({"company_id": company_id}).sort("created_at", -1)
    leads = []
    async for doc in cursor:
        doc["id"] = str(doc.pop("_id"))
        leads.append(doc)
    return leads

@router.post("/companies/{company_id}/sales-calls/schedule", response_model=SalesCallResponse, status_code=201)
async def schedule_sales_call(
    body: SalesCallCreate,
    company_id: str = Path(...),
    ctx: AuthContext = Depends(require_admin)
):
    # Verify Agent
    agent = await col_agents().find_one({"_id": ObjectId(body.agent_id), "company_id": company_id})
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
        
    sales_config = agent.get("sales_config")
    if not sales_config or not sales_config.get("sales_enabled"):
        raise HTTPException(status_code=400, detail="Sales features are not enabled for this agent")

    # Verify Lead
    lead = await col_leads().find_one({"_id": ObjectId(body.lead_id), "company_id": company_id})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
        
    now = datetime.now(timezone.utc)
    
    # Create Call Document
    doc = body.model_dump()
    doc["company_id"] = company_id
    doc["status"] = CallStatus.SCHEDULED.value
    doc["direction"] = "outbound"
    doc["lead_name"] = lead.get("name")
    doc["lead_email"] = lead.get("email")
    doc["source"] = "api"
    doc["created_at"] = now
    doc["updated_at"] = now
    doc["duration_seconds"] = 0
    
    res = await col_sales_calls().insert_one(doc)
    doc["id"] = str(res.inserted_id)
    
    logger.info(f"[SALES_CALL_CREATED] sales_call_id={doc['id']} company_id={company_id} agent_id={body.agent_id}")
    
    # Automatically "Queue" and "Dial" using mock telephony
    logger.info(f"[SALES_CALL_SCHEDULED] sales_call_id={doc['id']} dialing via mock provider")
    await col_sales_calls().update_one({"_id": res.inserted_id}, {"$set": {"status": CallStatus.RINGING.value}})
    logger.info(f"[SALES_CALL_RINGING] sales_call_id={doc['id']}")
    
    provider_call_id = await telephony_provider.create_call(
        to_phone=body.phone_number,
        from_phone="system_default",
        webhook_url=f"http://localhost:8000/api/v1/companies/{company_id}/sales-calls/{doc['id']}/webhook",
        metadata={"sales_call_id": doc["id"]}
    )
    
    doc["status"] = CallStatus.RINGING
    return doc

@router.get("/companies/{company_id}/sales-calls", response_model=List[SalesCallResponse])
async def list_sales_calls(
    company_id: str = Path(...),
    ctx: AuthContext = Depends(require_admin)
):
    cursor = col_sales_calls().find({"company_id": company_id}).sort("created_at", -1)
    calls = []
    async for doc in cursor:
        doc["id"] = str(doc.pop("_id"))
        calls.append(doc)
    return calls

async def generate_sales_summary(company_id: str, agent_id: str, sales_call_id: str, conversation_id: str, lead_id: str):
    logger.info(f"[SALES_CALL_SUMMARY_START] sales_call_id={sales_call_id}")
    try:
        agent = await col_agents().find_one({"_id": ObjectId(agent_id)})
        if not agent:
            return
            
        conv = await col_conversations().find_one({"_id": ObjectId(conversation_id)})
        if not conv:
            return
            
        history = []
        async for msg in col_messages().find({"conversation_id": conversation_id}).sort("created_at", 1):
            history.append({"role": msg["role"], "content": msg["text"]})
            
        if len(history) <= 1:
            logger.info(f"[SALES_CALL_SUMMARY_SKIPPED] sales_call_id={sales_call_id} reason=no_turns")
            return
            
        client = await AgentLLMClient.create(agent)
        
        prompt = """You are an expert sales analyst. Based on the following conversation, extract:
1. summary: A brief 2 sentence summary of the call.
2. customer_need: What does the customer want?
3. interested_products: A list of products they are interested in.
4. qualification_status: qualified, unqualified, or unknown.
5. objections: A bulleted list of objections.
6. next_action: What should the sales rep do next?
7. followup_required: true or false.

Format the output strictly as JSON with those exact keys. Do not hallucinate data. If not found, use null or []."""
        
        # Simple string-based extraction for this mock
        # In a real app, we'd use a strict JSON schema mode on the LLM
        response_tuple = await client.generate(prompt, history)
        response_content = response_tuple[0] or ""
        
        import json
        import re
        try:
            # Strip markdown json block if present
            cleaned = response_content.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            if cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
                
            match = re.search(r'\{.*\}', cleaned, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
            else:
                data = json.loads(cleaned)
        except:
            data = {"summary": "Could not parse JSON", "followup_required": True}
            
        summary = SalesCallSummary(
            customer_need=data.get("customer_need"),
            interested_products=data.get("interested_products", []),
            qualification_status=data.get("qualification_status"),
            objections=data.get("objections", []),
            next_action=data.get("next_action"),
            followup_required=str(data.get("followup_required")).lower() == "true",
            full_summary=data.get("summary")
        )
        
        await col_sales_calls().update_one({"_id": ObjectId(sales_call_id)}, {"$set": {"call_summary": summary.model_dump()}})
        
        # Update Lead
        lead_update = {}
        if data.get("qualification_status"):
            lead_update["qualification"] = data.get("qualification_status")
        if data.get("next_action"):
            lead_update["next_action"] = data.get("next_action")
            
        if lead_update:
            await col_leads().update_one({"_id": ObjectId(lead_id)}, {"$set": lead_update})
            
        logger.info(f"[SALES_CALL_SUMMARY_COMPLETE] sales_call_id={sales_call_id}")
    except Exception as e:
        logger.error(f"[SALES_CALL_SUMMARY_ERROR] err={e}")

from fastapi import Request

@router.post("/companies/{company_id}/sales-calls/{sales_call_id}/webhook", status_code=200)
async def sales_call_webhook(
    request: Request,
    company_id: str = Path(...),
    sales_call_id: str = Path(...),
):
    # Support both JSON (mock) and Form (Twilio)
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        data = await request.json()
        event_name = data.get("event")
        provider_call_id = data.get("provider_call_id")
    else:
        # Twilio form data
        form_data = await request.form()
        
        # Verify Signature if using Twilio
        if settings.telephony_provider == "twilio":
            signature = request.headers.get("X-Twilio-Signature", "")
            url = str(request.url)
            # Twilio validation requires strict matching of POST variables
            post_vars = {k: v for k, v in form_data.items()}
            # Access underlying verify_webhook method
            if hasattr(telephony_provider, "verify_webhook"):
                if not telephony_provider.verify_webhook(url, post_vars, signature):
                    logger.error("[SALES_CALL_WEBHOOK_REJECTED] Invalid Twilio Signature")
                    raise HTTPException(status_code=403, detail="Invalid signature")
        
        # Map Twilio CallStatus to our events
        twilio_status = form_data.get("CallStatus", "").lower()
        if twilio_status in ["initiated", "ringing"]:
            event_name = "ringing"
        elif twilio_status == "in-progress":
            event_name = "answered"
        elif twilio_status == "completed":
            event_name = "completed"
        elif twilio_status in ["failed", "no-answer", "canceled", "busy"]:
            event_name = "failed"
        else:
            event_name = "unknown"
            
        provider_call_id = form_data.get("CallSid")

    logger.info(f"[SALES_CALL_WEBHOOK] sales_call_id={sales_call_id} event={event_name}")
    
    class MockBody:
        event = event_name
        
    body = MockBody()
    logger.info(f"[SALES_CALL_WEBHOOK] sales_call_id={sales_call_id} event={body.event}")
    
    call = await col_sales_calls().find_one({"_id": ObjectId(sales_call_id), "company_id": company_id})
    if not call:
        logger.error("[SALES_CALL_WEBHOOK_REJECTED] Call not found")
        raise HTTPException(status_code=404, detail="Call not found")
        
    current_status = call.get("status")
    
    # Idempotency
    if current_status in [CallStatus.COMPLETED.value, CallStatus.FAILED.value, CallStatus.NO_ANSWER.value]:
        return {"status": "ignored"}
        
    updates = {}
    now = datetime.now(timezone.utc)
    
    if body.event == "ringing":
        updates["status"] = CallStatus.RINGING.value
        
    elif body.event == "answered":
        updates["status"] = CallStatus.IN_PROGRESS.value
        updates["started_at"] = now
        
        if not call.get("conversation_id"):
            conv = await conversation_service.create_conversation(
                company_id=company_id,
                agent_id=call["agent_id"],
                direction="outbound",
                caller_phone=call["phone_number"],
                scheduled_call_id=sales_call_id
            )
            updates["conversation_id"] = str(conv["_id"])
            logger.info(f"[SALES_AI_SESSION_CREATED] conversation_id={updates['conversation_id']}")

            
    elif body.event == "completed":
        updates["status"] = CallStatus.COMPLETED.value
        updates["ended_at"] = now
        if call.get("started_at"):
            if call["started_at"].tzinfo is None:
                started = call["started_at"].replace(tzinfo=timezone.utc)
            else:
                started = call["started_at"]
            updates["duration_seconds"] = int((now - started).total_seconds())
            
        if call.get("conversation_id"):
            await conversation_service.end_conversation(company_id, call["conversation_id"], status="completed")
            logger.info(f"[SALES_AI_SESSION_ENDED] conversation_id={call['conversation_id']}")
            asyncio.create_task(generate_sales_summary(company_id, call["agent_id"], sales_call_id, call["conversation_id"], call["lead_id"]))
            
    elif body.event in ["failed", "no_answer"]:
        updates["status"] = body.event
        updates["ended_at"] = now
        
    if updates:
        await col_sales_calls().update_one({"_id": ObjectId(sales_call_id)}, {"$set": updates})
        logger.info(f"[SALES_CALL_STATE_CHANGE] sales_call_id={sales_call_id} new_state={updates['status']}")
        
    return {"status": "processed"}

from fastapi.responses import Response

@router.post("/companies/{company_id}/sales-calls/{sales_call_id}/twiml")
async def generate_twiml(company_id: str, sales_call_id: str):
    """Returns the XML instruction to connect the Twilio call to our media stream."""
    if hasattr(telephony_provider, "get_twiml_media_stream"):
        # Construct WebSocket URL dynamically
        wss_url = settings.app_base_url.replace("http", "ws") + f"/api/v1/companies/{company_id}/sales-calls/{sales_call_id}/stream"
        xml = telephony_provider.get_twiml_media_stream(wss_url)
        return Response(content=xml, media_type="application/xml")
    return Response(content='<Response></Response>', media_type="application/xml")
