import asyncio
import json
import base64
import logging
import os
import httpx
import websockets
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from dotenv import load_dotenv
import os

env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env")
load_dotenv(env_path)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Advanced Voice Agent"])

DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = "21m00Tcm4TlvDq8ikWAM" # Default voice

@router.post("/webhook/exotel/advanced/{company_id}/{agent_id}/voice")
async def exotel_voice_webhook(company_id: str, agent_id: str, request: Request):
    """
    Inbound Call Handler: Exotel dials in and we return Exotel XML.
    """
    form = await request.form()
    caller = form.get("From", "Unknown")
    to_number = form.get("To", "Unknown")
    call_sid = form.get("CallSid", "")
    logger.info(f"📞 Exotel Inbound call received from {caller} → {to_number} CallSid={call_sid} for agent {agent_id}")

    host = request.headers.get("host", "")
    scheme = "wss" if "localhost" not in host and "127.0.0.1" not in host else "ws"
    http_scheme = "https" if scheme == "wss" else "http"
    ws_url = f"{scheme}://{host}/api/v1/webhook/exotel/advanced/{company_id}/{agent_id}/media-stream?caller={caller}"
    recording_cb = f"{http_scheme}://{host}/api/v1/webhook/exotel/advanced/{company_id}/{agent_id}/recording-status"

    contact_name = request.query_params.get("contact_name", "")
    
    # Return pure Exotel Call Control XML
    exotel_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="{ws_url}" />
    </Connect>
</Response>
"""
    return Response(content=exotel_xml, media_type="text/xml")


@router.post("/webhook/exotel/advanced/{company_id}/{agent_id}/recording-status")
async def exotel_recording_status(company_id: str, agent_id: str, request: Request):
    """
    Twilio calls this when a recording is ready.
    We save the recording URL to the conversation so the frontend can display it.
    """
    form = await request.form()
    recording_url = form.get("RecordingUrl", "")
    recording_sid = form.get("RecordingSid", "")
    call_sid = form.get("CallSid", "")
    duration = form.get("RecordingDuration", "0")
    
    logger.info(f"🎙️ Recording ready: CallSid={call_sid} RecordingSid={recording_sid} URL={recording_url}")
    
    if recording_url and call_sid:
        try:
            from core.database import col_conversations
            # Add .mp3 extension for direct browser playback
            mp3_url = recording_url + ".mp3"
            await col_conversations().update_one(
                {"call_sid": call_sid},
                {"$set": {
                    "recording_url": mp3_url,
                    "recording_sid": recording_sid,
                    "recording_duration": int(duration) if duration else 0,
                }}
            )
            logger.info(f"✅ Recording URL saved for CallSid={call_sid}")
        except Exception as e:
            logger.error(f"Failed to save recording URL: {e}")
    
    return Response(content="OK", media_type="text/plain")



async def fetch_llm_response(conversation_history):
    """
    STEP 2: Brain - Groq LLM inference for extremely fast text generation.
    """
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    # Enforce short, conversational responses for voice.
    system_prompt = {
        "role": "system",
        "content": (
            "You are Zenia, the official AI Voice Representative for 'ZeniaOne'. "
            "ZeniaOne is a cutting-edge Enterprise AI Voice & Chat Agent platform that creates zero-latency, highly intelligent AI agents. "
            "You speak naturally like a real human. Use conversational fillers like 'hmm', 'acchha', 'dekhiye', or 'right' where appropriate to sound authentic. "
            "CRITICAL RULES: "
            "1. BE EXTREMELY CONVERSATIONAL AND HUMAN-LIKE. Do not sound like a robot reading a script. "
            "2. Keep your responses short, crisp, and interactive (1-2 sentences). End with a natural question to keep the conversation flowing. "
            "3. NEVER use emojis, markdown (* or #), or bullet points. "
            "4. Seamlessly switch between Hindi, Hinglish, and English based on the user's tone. "
            "5. If they ask about ZeniaOne, proudly explain that we can automate customer support, lead generation, and sales with AI that speaks exactly like a human, 24/7, without taking any leaves! "
            "6. Always listen carefully. If they say 'ok' or 'haan', just say 'haan ji' or 'right' and continue. "
            "7. Your goal is to be helpful, polite, and build trust in ZeniaOne's technology."
        )
    }
    
    messages = [system_prompt] + conversation_history

    payload = {
        "model": "llama3-8b-8192", 
        "messages": messages,
        "temperature": 0.5,
        "max_tokens": 100
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=headers, json=payload, timeout=10.0)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"Error fetching from Groq: {e}")
        return "I'm sorry, I am having a little trouble connecting to my brain right now."


async def text_to_speech_and_stream(text: str, twilio_ws: WebSocket, stream_sid: str, cancel_event: asyncio.Event):
    """
    STEP 3: Mouth - Stream Sarvam TTS audio back to Twilio.
    Includes BARGE-IN checking!
    """
    logger.info(f"🗣️ AI Speaking: {text}")
    
    from modules.sarvam_tts import realtime_tts_stream
    from modules.audio_utils import sarvam_to_twilio
    
    try:
        # Sarvam TTS stream yields linear16 24000Hz PCM
        chunks_yielded = 0
        async for chunk in realtime_tts_stream(text, language="hi-IN", speaker="ritu"):
            chunks_yielded += 1
            # BARGE-IN CHECK: If user started speaking, cancel_event will be set!
            if cancel_event.is_set():
                logger.warning("🛑 BARGE-IN TRIGGERED! Stopping TTS playback immediately.")
                # Send Twilio a 'clear' message to flush any queued audio
                await twilio_ws.send_json({
                    "event": "clear",
                    "streamSid": stream_sid,
                    "stream_sid": stream_sid
                })
                break # Break the loop, stop sending audio
            
            if chunk:
                # Convert 24kHz linear16 PCM to 8kHz mu-law for Twilio
                from modules.audio_utils import sarvam_to_twilio
                mulaw_chunk = sarvam_to_twilio(chunk, input_rate=24000)
                audio_b64 = base64.b64encode(mulaw_chunk).decode("utf-8")
                await twilio_ws.send_json({
                    "event": "media",
                    "streamSid": stream_sid,
                    "stream_sid": stream_sid,
                    "media": {"payload": audio_b64}
                })
        
        if chunks_yielded == 0 and not cancel_event.is_set():
            logger.warning("🎙️ Sarvam stream empty, executing MP3 EdgeTTS fallback...")
            from modules.sarvam_tts import fallback_neural_tts
            import sys
            import os
            # Ensure legacy path is accessible
            legacy_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            if legacy_root not in sys.path:
                sys.path.insert(0, legacy_root)
            from modules.audio_utils import mp3_to_mulaw
            
            mp3_bytes = await fallback_neural_tts(text, speaker="ritu")
            if mp3_bytes:
                mulaw_bytes = mp3_to_mulaw(mp3_bytes)
                # Exotel requires 20ms chunks (160 bytes for 8kHz mu-law) to prevent payload dropping
                chunk_size = 160
                for i in range(0, len(mulaw_bytes), chunk_size):
                    if cancel_event.is_set():
                        await twilio_ws.send_json({"event": "clear", "streamSid": stream_sid})
                        break
                    
                    audio_b64 = base64.b64encode(mulaw_bytes[i:i+chunk_size]).decode("utf-8")
                    await twilio_ws.send_json({
                        "event": "media",
                        "streamSid": stream_sid,
                        "media": {"payload": audio_b64}
                    })
                    # Sleep slightly less than 20ms to allow buffering but prevent rapid-fire dropping
                    await asyncio.sleep(0.01)
                
    except Exception as e:
        logger.error(f"TTS Streaming Error: {e}")


from services.conversation_service import create_conversation, add_message, end_conversation

@router.websocket("/webhook/exotel/advanced/{company_id}/{agent_id}/media-stream")
async def exotel_media_stream(company_id: str, agent_id: str, websocket: WebSocket):
    """
    STEP 1: The main WebSockets pipeline linking Exotel <-> Deepgram <-> Groq <-> Sarvam
    """
    logger.info(f"Incoming WS connection for {company_id}/{agent_id}")
    try:
        await websocket.accept()
        logger.info(f"🔌 Twilio Media Stream Connected for agent {agent_id}!")
    except Exception as e:
        logger.error(f"Failed to accept WS: {e}")
        return

    stream_sid = None
    call_sid = None
    conversation_id = None
    conversation_history = []
    
    # Barge-in event: When set, the TTS streaming function will stop sending audio.
    cancel_event = asyncio.Event()

    # Deepgram WebSocket URL for real-time transcription
    deepgram_url = "wss://api.deepgram.com/v1/listen?encoding=mulaw&sample_rate=8000&channels=1&endpointing=300&interim_results=true&model=nova-2&language=hi&smart_format=true"

    try:
        async with websockets.connect(
            deepgram_url, 
            additional_headers={"Authorization": f"Token {DEEPGRAM_API_KEY}"}
        ) as deepgram_ws:
            
            # --- TASK A: Receive Audio from Twilio, Send to Deepgram ---
            async def receive_from_twilio():
                nonlocal stream_sid, call_sid, conversation_id, company_id
                media_count = 0
                try:
                    while True:
                        message = await websocket.receive_text()
                        data = json.loads(message)
                        
                        if data['event'] == 'start':
                            start_data = data.get('start', {})
                            stream_sid = start_data.get('streamSid') or start_data.get('stream_sid', 'unknown_stream')
                            
                            logger.info(f"✅ Exotel Start Event received. Stream SID: {stream_sid}")
                            
                            # Exotel might not send callSid in standard format, so we check query params first
                            query_call_sid = websocket.query_params.get("call_sid")
                            call_sid = query_call_sid or start_data.get('callSid') or start_data.get('CallSid') or start_data.get('call_sid', 'local_test_' + stream_sid)
                            
                            custom_params = start_data.get('customParameters', {})
                            # Use query parameter first (Exotel direct WSS), fallback to customParameters (Twilio XML)
                            contact_name = websocket.query_params.get("contact_name") or custom_params.get('contactName', '')
                            channel_id = websocket.query_params.get("channel_id")
                            
                            # 💾 [DB STEP] Save New Conversation
                            caller_phone = websocket.query_params.get("caller") or custom_params.get('caller') or "Unknown"
                            conv_doc = await create_conversation(
                                company_id=company_id,
                                agent_id=agent_id,
                                call_sid=call_sid,
                                caller_phone=caller_phone,
                                channel_id=channel_id
                            )
                            conversation_id = str(conv_doc["_id"])
                            company_id = str(conv_doc.get("company_id", company_id)) # Use true company ID from DB
                            
                            # Initial Greeting (Zero Latency)
                            if contact_name:
                                greeting = f"Hello {contact_name} kaise ho? Main ZeniaOne se baat kar rahi hu. Bataye, hum aapki kya help kar sakte hain?"
                            else:
                                greeting = "Hello, I am Zenia One assistant. How can I help you today?"
                            
                            conversation_history.append({"role": "assistant", "content": greeting})
                            
                            # 💾 [DB STEP] Log Greeting Message
                            await add_message(company_id, conversation_id, "assistant", greeting)
                            
                            asyncio.create_task(text_to_speech_and_stream(greeting, websocket, stream_sid, cancel_event))
                            
                        elif data['event'] == 'media':
                            media_count += 1
                            if media_count == 1:
                                logger.info(f"🔊 Received first media packet from Exotel!")
                            if media_count % 50 == 0:
                                logger.info(f"🔊 Received {media_count} media packets from Exotel...")
                            # Send raw audio bytes to Deepgram
                            audio_payload = data['media']['payload']
                            audio_bytes = base64.b64decode(audio_payload)
                            await deepgram_ws.send(audio_bytes)
                            
                        elif data['event'] == 'stop':
                            break
                except WebSocketDisconnect:
                    logger.info("Twilio disconnected.")
                except Exception as e:
                    logger.error(f"Twilio Receive Error: {e}")

            # --- TASK B: Receive Transcripts from Deepgram ---
            async def receive_from_deepgram():
                try:
                    while True:
                        dg_message = await deepgram_ws.recv()
                        dg_data = json.loads(dg_message)
                        
                        if "channel" in dg_data:
                            transcript = dg_data["channel"]["alternatives"][0]["transcript"].strip()
                            
                            if not transcript:
                                continue

                            is_final = dg_data.get("is_final", False)

                            if not is_final:
                                # THE BARGE-IN EFFECT!
                                # If the user is speaking, and we haven't already cancelled the AI, do it now.
                                if not cancel_event.is_set():
                                    logger.info(f"⚡ User started speaking (Interim): {transcript} -> TRIGGERING BARGE-IN")
                                    cancel_event.set()
                            
                            else:
                                # User finished speaking (is_final == True)
                                logger.info(f"🧑 User Said (Final): {transcript}")
                                
                                # 1. Clear the cancel event so the AI can speak again
                                cancel_event.clear()
                                
                                # 2. Save to conversation context
                                conversation_history.append({"role": "user", "content": transcript})
                                
                                # 💾 [DB STEP] Log User Message
                                if conversation_id:
                                    await add_message(company_id, conversation_id, "user", transcript)
                                
                                # 3. Fetch LLM Response (Brain)
                                ai_response = await fetch_llm_response(conversation_history)
                                conversation_history.append({"role": "assistant", "content": ai_response})
                                
                                # 💾 [DB STEP] Log AI Message
                                if conversation_id:
                                    await add_message(company_id, conversation_id, "assistant", ai_response)
                                
                                # 4. Speak it out (Mouth)
                                if stream_sid:
                                    asyncio.create_task(text_to_speech_and_stream(ai_response, websocket, stream_sid, cancel_event))
                                
                except websockets.exceptions.ConnectionClosed:
                    logger.info("Deepgram connection closed.")
                except Exception as e:
                    logger.error(f"Deepgram Receive Error: {e}")

            # Run both tasks concurrently
            await asyncio.gather(
                receive_from_twilio(),
                receive_from_deepgram()
            )

    except Exception as e:
        logger.error(f"Voice Pipeline Failed: {e}")
        try:
            await websocket.send_text(json.dumps({"event": "error", "message": str(e)}))
        except:
            pass
    finally:
        # 💾 [DB STEP] End Conversation
        if conversation_id:
            await end_conversation(company_id, conversation_id, status="completed")
        await websocket.close()

@router.post("/webhook/exotel/advanced/{company_id}/{agent_id}/status")
async def exotel_status_webhook(company_id: str, agent_id: str, request: Request):
    """Callback to receive terminal call status from Exotel."""
    try:
        # Exotel sends POST with form data
        form_data = await request.form()
        call_sid = form_data.get("CallSid")
        status = form_data.get("Status")
        
        if not call_sid or not status:
            return {"status": "ok"}
            
        logger.info(f"Exotel Status Webhook: CallSid={call_sid}, Status={status}")
        
        # Determine internal status based on Exotel status
        internal_status = status.lower()
        if internal_status in ["completed"]:
            pass # Usually handled by websocket close, but good to catch
        elif internal_status in ["failed", "busy", "no-answer", "canceled", "failed"]:
            internal_status = "hung-up" # Map to what UI expects for failed/missed
            
        from core.database import col_conversations
        from datetime import datetime, timezone
        
        update_data = {
            "status": internal_status,
            "ended_at": datetime.now(timezone.utc)
        }
        
        # Capture Talk Time if provided by Exotel
        duration = form_data.get("Duration") or form_data.get("CallDuration")
        if duration and duration.isdigit():
            update_data["duration_seconds"] = int(duration)
            
        recording_url = form_data.get("RecordingUrl")
        if recording_url:
            update_data["recording_url"] = recording_url
            
        await col_conversations().update_one(
            {"call_sid": call_sid},
            {"$set": update_data}
        )
        
    except Exception as e:
        logger.error(f"Error in Exotel Status Webhook: {e}")
        
    return {"status": "ok"}
