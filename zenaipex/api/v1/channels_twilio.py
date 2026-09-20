"""
Zenaipex AI — Twilio Channels API and Webhooks.

Handles inbound Twilio calls, providing TwiML and the WebSocket media stream.
"""
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect, Depends
from fastapi.responses import HTMLResponse, Response, JSONResponse
from typing import Optional
import uuid
import json
import asyncio
import time
from urllib.parse import urlparse

from core.database import col_channels
from services.agent_service import load_agent_for_call
from services.conversation_service import create_conversation, end_conversation, add_message
from services.usage_service import increment_usage, check_call_minute_limit, check_ai_credit_limit
from ai.llm import AgentLLMClient
from ai.rag import get_rag_pipeline

import sys
import os
# Add legacy root to path so we can import legacy audio modules
ZENAIPEX_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LEGACY_ROOT = os.path.dirname(ZENAIPEX_ROOT)
if LEGACY_ROOT not in sys.path:
    sys.path.insert(0, LEGACY_ROOT)

from modules.audio_utils import (
    AudioBuffer, SilenceDetector, audio_to_base64, mp3_to_mulaw
)
from modules.sarvam_stt import TrueStreamingSTT
from modules.sarvam_tts import SarvamRealtimeTTS
import logging

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Twilio Webhooks"])

# ── 1. HTTP Webhook (TwiML) ───────────────────────────────────────────────────

@router.post("/webhook/twilio/{company_slug}/voice")
async def twilio_voice_webhook(company_slug: str, request: Request):
    """
    Inbound Twilio voice webhook.
    Returns TwiML instructing Twilio to open a WebSocket to our /media-stream endpoint.
    """
    form = await request.form()
    phone_number = form.get("To")  # The Twilio number that was dialed
    caller = form.get("From")
    call_sid = form.get("CallSid")

    logger.info(f"📞 Inbound call from {caller} to {phone_number} (company: {company_slug})")

    # The Twilio endpoint needs the wss:// host
    host = request.headers.get("host", "")
    scheme = "wss" if "localhost" not in host and "127.0.0.1" not in host else "ws"
    # Note: Using the generic /webhook/twilio/media-stream endpoint,
    # the company will be resolved by the phone number dialed,
    # or passed as a query param.
    ws_url = f"{scheme}://{host}/api/v1/webhook/twilio/media-stream"

    # Minimal TwiML to connect the stream
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="{ws_url}" />
    </Connect>
</Response>
"""
    return Response(content=twiml, media_type="text/xml")


# ── 2. Background Audio Helper ────────────────────────────────────────────────
import base64
BACKGROUND_AUDIO_CACHE = []

def load_background_audio():
    global BACKGROUND_AUDIO_CACHE
    try:
        from pydub import AudioSegment
        audio_path = os.path.join(LEGACY_ROOT, "asset", "Office Background Ambience _ Free Sound Effect-[AudioTrimmer.com].mp3")
        if not os.path.exists(audio_path):
            return
        audio = AudioSegment.from_mp3(audio_path).set_channels(1).set_frame_rate(8000).set_sample_width(2) - 1
        pcm_data = audio.raw_data
        try:
            import audioop
        except ImportError:
            import audioop_lts as audioop
        mulaw_data = audioop.lin2ulaw(pcm_data, 2)
        chunk_size = 160
        BACKGROUND_AUDIO_CACHE = [base64.b64encode(mulaw_data[i:i + chunk_size]).decode() 
                                  for i in range(0, len(mulaw_data), chunk_size) if len(mulaw_data[i:i+chunk_size]) == chunk_size]
    except Exception as e:
        logger.warning(f"Could not load background audio: {e}")

load_background_audio()

async def start_background_audio_loop(websocket: WebSocket, stream_sid: str, session: dict):
    if not BACKGROUND_AUDIO_CACHE or not session.get("enable_background_audio", True):
        return
    chunk_index = 0
    try:
        while not session.get("call_ended", False):
            chunk_b64 = BACKGROUND_AUDIO_CACHE[chunk_index]
            try:
                await websocket.send_json({
                    "event": "media",
                    "streamSid": stream_sid,
                    "media": {"payload": chunk_b64}
                })
            except Exception:
                break
            chunk_index = (chunk_index + 1) % len(BACKGROUND_AUDIO_CACHE)
            await asyncio.sleep(0.02)
    except asyncio.CancelledError:
        pass


# ── 3. Voice Processing Loop ──────────────────────────────────────────────────

async def process_voice_turn(websocket: WebSocket, stream_sid: str, session: dict, transcript: str):
    """Multi-tenant voice processing pipeline (STT -> RAG -> LLM -> TTS)."""
    transcript = transcript.strip()
    if not transcript:
        return
        
    company_id = session["company_id"]
    agent_id = session["agent_id"]
    conversation_id = session["conversation_id"]
    llm_client: AgentLLMClient = session["llm_client"]
    rag_pipeline = session["rag_pipeline"]
    
    # 1. Add user message to transcript
    await add_message(company_id, conversation_id, "user", transcript, session["language"])
    
    # 2. Check for goodbye
    from realtime_app import detect_goodbye, detect_booking_confirmed, normalize_text_for_tts, should_end_call_after_response
    if detect_goodbye(transcript, session["language"]):
        session["call_ended"] = True
        return
        
    # 3. RAG Retrieval
    context_docs = None
    if rag_pipeline.should_retrieve(transcript, session["language"]):
        context_docs = await rag_pipeline.retrieve(transcript)
        session["rag_queries"] += 1
        
    # 4. LLM Generation + Streaming TTS
    try:
        session["is_speaking"] = True
        session["llm_api_calls"] += 1
        
        # We use standard Sarvam TTS for this integration
        from modules.sarvam_tts import SarvamRealtimeTTS
        speaker = session["agent_config"].get("tts_voice", "anushka")
        
        if not session.get("tts_client"):
            session["tts_client"] = SarvamRealtimeTTS(language_code=session["language"], speaker=speaker)
            await session["tts_client"].connect()
            
        tts = session["tts_client"]
        
        response_text = ""
        sentence_buffer = ""
        import re
        sentence_end_pattern = re.compile(r'[.!?।॥]')
        
        current_date = time.strftime("%A, %B %d, %Y")
        company_name = session["company_name"]
        
        # Async generator for LLM stream
        async for token in llm_client.stream(
            user_message=transcript,
            conversation_history=session["conversation_history"],
            context_docs=context_docs,
            language=session["language"],
            current_date=current_date,
            company_name=company_name
        ):
            response_text += token
            sentence_buffer += token
            
            if sentence_end_pattern.search(sentence_buffer) and len(sentence_buffer) >= 15:
                sentence_to_speak = sentence_buffer.strip()
                sentence_buffer = ""
                
                # Clean hallucinated prefixes
                if sentence_to_speak.lower().startswith(('user:', 'உசர்:', 'பயனர்:')):
                    continue
                if sentence_to_speak.lower().startswith('assistant:'):
                    sentence_to_speak = sentence_to_speak.split(':', 1)[1].strip()
                    
                normalized_text = normalize_text_for_tts(sentence_to_speak, session["language"])
                await tts.send_text(normalized_text + " ")
                await tts.flush()
                
                # Receive audio
                session["tts_api_calls"] += 1
                async for audio_chunk in tts.receive_stream():
                    mulaw_audio = mp3_to_mulaw(audio_chunk)
                    if mulaw_audio:
                        try:
                            await websocket.send_json({
                                "event": "media",
                                "streamSid": stream_sid,
                                "media": {"payload": audio_to_base64(mulaw_audio)}
                            })
                        except Exception:
                            break
                            
        # Flush remaining buffer
        if sentence_buffer.strip():
            sentence_to_speak = sentence_buffer.strip()
            if not sentence_to_speak.lower().startswith(('user:', 'உசர்:', 'பயனர்:')):
                if sentence_to_speak.lower().startswith('assistant:'):
                    sentence_to_speak = sentence_to_speak.split(':', 1)[1].strip()
                normalized_text = normalize_text_for_tts(sentence_to_speak, session["language"])
                await tts.send_text(normalized_text)
                await tts.flush()
                session["tts_api_calls"] += 1
                async for audio_chunk in tts.receive_stream():
                    mulaw_audio = mp3_to_mulaw(audio_chunk)
                    if mulaw_audio:
                        try:
                            await websocket.send_json({
                                "event": "media",
                                "streamSid": stream_sid,
                                "media": {"payload": audio_to_base64(mulaw_audio)}
                            })
                        except Exception:
                            break
                            
        # Send playback mark
        try:
            await websocket.send_json({
                "event": "mark",
                "streamSid": stream_sid,
                "mark": {"name": f"response_{int(time.time())}"}
            })
        except:
            pass
            
        session["is_speaking"] = False
        
        # Save assistant message
        await add_message(company_id, conversation_id, "assistant", response_text, session["language"])
        
        # Update history
        session["conversation_history"].append({"role": "user", "content": transcript})
        session["conversation_history"].append({"role": "assistant", "content": response_text})
        
        if should_end_call_after_response(response_text, transcript, session):
            session["call_ended"] = True
            
    except Exception as e:
        logger.error(f"Voice pipeline error: {e}")
        session["is_speaking"] = False


# ── 4. WebSocket Media Stream ─────────────────────────────────────────────────

@router.websocket("/webhook/twilio/media-stream")
async def media_stream_websocket(websocket: WebSocket):
    """
    Main entrypoint for the Twilio media stream.
    Loads tenant config based on the Twilio phone number dialed.
    """
    await websocket.accept()
    
    session = {
        "call_sid": "",
        "stream_sid": "",
        "caller": "",
        "called_number": "",
        "audio_buffer": AudioBuffer(target_duration_ms=40),
        "silence_detector": SilenceDetector(threshold=250, silence_duration_ms=800, min_speech_duration_ms=800),
        "is_speaking": False,
        "call_ended": False,
        "start_time": time.time(),
        "conversation_history": [],
        "rag_queries": 0,
        "stt_api_calls": 0,
        "tts_api_calls": 0,
        "llm_api_calls": 0,
        
        # Multi-tenant state (loaded on 'start' event)
        "company_id": None,
        "company_name": None,
        "agent_id": None,
        "conversation_id": None,
        "agent_config": None,
        "language": "en-IN",  # Default, overridden by agent config
        "llm_client": None,
        "rag_pipeline": None,
        "streaming_stt": None,
        "tts_client": None,
        "enable_background_audio": True,
    }
    
    bg_audio_task = None
    
    try:
        while not session["call_ended"]:
            message = await websocket.receive_text()
            data = json.loads(message)
            event_type = data.get("event")
            
            if event_type == "start":
                # 1. Initialize call details
                start_data = data.get("start", {})
                session["call_sid"] = start_data.get("callSid", "")
                session["stream_sid"] = start_data.get("streamSid", "")
                
                # Twilio doesn't send To/From in the 'start' event of a media stream
                # unless explicitly added as custom parameters in TwiML.
                # For this integration, we parse them from custom parameters.
                custom_params = start_data.get("customParameters", {})
                phone_number = custom_params.get("called_number")
                caller = custom_params.get("caller")
                
                # If custom parameters aren't provided, we have to look up the CallSid
                # in the conversation DB to find the number, assuming the HTTP webhook 
                # created the conversation first. But let's create the conversation here 
                # using the phone_number we get.
                
                # In this demo, we'll assume the webhook passed them in custom parameters, 
                # OR we look up the CallSid from the Conversation we created in the HTTP webhook.
                from services.conversation_service import find_conversation_by_call_sid
                
                # First attempt: load agent using the dialed phone number
                agent_context = None
                if phone_number:
                    agent_context = await load_agent_for_call(phone_number)
                
                # Fallback: if we didn't get phone_number, try to find a recently created 
                # conversation by call_sid, or default to the first active channel if dev mode.
                if not agent_context:
                    # Dev mode fallback: just grab the RK Hospital agent for testing
                    from core.database import col_channels
                    channel = await col_channels().find_one({"is_active": True})
                    if channel:
                        agent_context = await load_agent_for_call(channel["phone_number"])
                
                if not agent_context:
                    logger.error(f"Could not resolve agent for call {session['call_sid']}")
                    await websocket.close()
                    return
                    
                # 2. Check Plan Limits
                if not await check_call_minute_limit(agent_context["company_id"]):
                    logger.warning(f"Company {agent_context['company_id']} exceeded call minute limit")
                    await websocket.close()
                    return

                if not await check_ai_credit_limit(agent_context["company_id"]):
                    logger.warning(f"Company {agent_context['company_id']} exceeded AI credit limit")
                    await websocket.close()
                    return
                    
                # 3. Setup Multi-Tenant Context
                agent = agent_context["agent"]
                session["company_id"] = agent_context["company_id"]
                session["company_name"] = agent_context["company"]["name"]
                session["agent_id"] = str(agent["_id"])
                session["agent_config"] = agent
                session["language"] = agent.get("default_language", "en-IN")
                session["enable_background_audio"] = agent.get("enable_background_audio", True)
                
                # 4. Initialize Multi-Tenant Clients
                try:
                    session["llm_client"] = await AgentLLMClient.create(agent)
                except RuntimeError as e:
                    # If we cannot resolve a provider, we must disconnect or say something
                    return templates.TemplateResponse(
                        "twilio_disconnect.xml", 
                        {"request": request, "message": str(e)}, 
                        media_type="application/xml"
                    )
                session["rag_pipeline"] = get_rag_pipeline(agent_context["company_id"], agent)
                
                # 5. Create Conversation Record
                conv = await create_conversation(
                    company_id=session["company_id"],
                    agent_id=session["agent_id"],
                    channel_id=str(agent_context["channel"]["_id"]),
                    call_sid=session["call_sid"],
                    caller_phone=caller,
                    direction="inbound",
                    language=session["language"]
                )
                session["conversation_id"] = str(conv["_id"])
                
                logger.info(f"✅ Call started. Tenant: {session['company_name']}, Agent: {agent['name']}")
                
                # 6. Initialize STT
                session["streaming_stt"] = TrueStreamingSTT(
                    language_code=session["language"],
                    model="saaras:v2"
                )
                await session["streaming_stt"].connect()
                
                # 7. Start Background Audio
                bg_audio_task = asyncio.create_task(
                    start_background_audio_loop(websocket, session["stream_sid"], session)
                )
                
                # 8. Send Greeting
                from realtime_app import normalize_text_for_tts
                greeting = agent.get("greeting_messages", {}).get(session["language"], "Hello!")
                greeting = greeting.format(company_name=session["company_name"])
                
                session["is_speaking"] = True
                
                # We use Sarvam TTS directly for the greeting
                speaker = agent.get("tts_voice", "anushka")
                session["tts_client"] = SarvamRealtimeTTS(language_code=session["language"], speaker=speaker)
                await session["tts_client"].connect()
                
                normalized_greeting = normalize_text_for_tts(greeting, session["language"])
                await session["tts_client"].send_text(normalized_greeting)
                await session["tts_client"].flush()
                
                async for audio_chunk in session["tts_client"].receive_stream():
                    mulaw_audio = mp3_to_mulaw(audio_chunk)
                    if mulaw_audio:
                        await websocket.send_json({
                            "event": "media",
                            "streamSid": session["stream_sid"],
                            "media": {"payload": audio_to_base64(mulaw_audio)}
                        })
                
                await websocket.send_json({
                    "event": "mark",
                    "streamSid": session["stream_sid"],
                    "mark": {"name": f"greeting_done"}
                })
                
                session["is_speaking"] = False
                await add_message(session["company_id"], session["conversation_id"], "assistant", greeting, session["language"])
                session["conversation_history"].append({"role": "assistant", "content": greeting})
                
            elif event_type == "media":
                if session["is_speaking"]:
                    continue # Ignore audio while agent is speaking
                    
                payload = data["media"]["payload"]
                audio_chunk = base64.b64decode(payload)
                session["audio_buffer"].add_audio(audio_chunk)
                
                while session["audio_buffer"].has_chunk():
                    chunk = session["audio_buffer"].get_chunk()
                    session["accumulated_audio"] += chunk
                    
                    speech_state = session["silence_detector"].process_audio_chunk(chunk)
                    
                    if speech_state == "SPEECH_STARTED":
                        pass
                    elif speech_state == "SPEECH_ENDED":
                        audio_to_process = session["accumulated_audio"]
                        session["accumulated_audio"] = b""
                        
                        # Send to STT
                        if session["streaming_stt"] and len(audio_to_process) > 8000: # at least 1s
                            session["stt_api_calls"] += 1
                            result = await session["streaming_stt"].process_audio_chunk(audio_to_process, is_final=True)
                            if result and result.transcript:
                                # Process the turn
                                asyncio.create_task(
                                    process_voice_turn(websocket, session["stream_sid"], session, result.transcript)
                                )
                                
            elif event_type == "mark":
                # Used to know when playback finishes
                session["is_speaking"] = False
                
            elif event_type == "stop":
                session["call_ended"] = True
                break
                
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        session["call_ended"] = True
        
        # Cleanup tasks
        if bg_audio_task:
            bg_audio_task.cancel()
            
        # Close STT/TTS
        if session.get("streaming_stt"):
            await session["streaming_stt"].close()
        if session.get("tts_client"):
            await session["tts_client"].close()
        if session.get("llm_client"):
            await session["llm_client"].close()
            
        # Update Usage & Conversation
        if session.get("company_id") and session.get("conversation_id"):
            duration = time.time() - session["start_time"]
            await end_conversation(
                company_id=session["company_id"],
                conversation_id=session["conversation_id"],
                status="completed"
            )
            
            await increment_usage(
                company_id=session["company_id"],
                call_duration_seconds=duration,
                stt_calls=session["stt_api_calls"],
                tts_calls=session["tts_api_calls"],
                rag_queries=session["rag_queries"],
                direction="inbound"
            )
        
        logger.info(f"Call ended for session {session.get('call_sid')}")
