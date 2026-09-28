import asyncio
import json
import time
import sys
import os

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

# Add zenaipex root to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.security import create_access_token
import websockets

COMPANY_ID = "6a990b403e9b17bef89acf87"
AGENT_ID = "6a990b403e9b17bef89acf8b"
USER_ID = "6a990b403e9b17bef89acf83"
WS_URL = f"ws://127.0.0.1:8002/api/v1/companies/{COMPANY_ID}/agents/{AGENT_ID}/voice-stream"

TEST_QUESTIONS = [
    ("User Prompt 1 (Exact User Query with Hinglish & STT distortions)", 
     "main hello Main Kya Kah Raha Hun ke bare mein aap Puri Jankari mujhe de sakte ho Vrindavan Kya Hai Kyon use hota hai best Akshara to bataiye"),
    ("User Prompt 2 (System Capabilities in Hinglish)", 
     "aapke paas kis kis cheez ki jaankari hai aur aap kya kya kar sakte ho?"),
    ("User Prompt 3 (Technical & Integration Hard Question)", 
     "Agar mujhe apni company ke documents upload karke customer care voice agent setup karna ho to pura process kya hai?"),
    ("User Prompt 4 (Features & Telephony Comparison)",
     "ZeniaOne ke main features kya hain aur Twilio calling kaise connect hoti hai?")
]

async def run_voice_test():
    token = create_access_token({"sub": USER_ID})
    print(f"Generated JWT token for user: {USER_ID}")

    async with websockets.connect(WS_URL) as ws:
        print("Connected to WebSocket voice stream")
        
        # 1. Send auth token
        await ws.send(json.dumps({"token": token}))
        
        # Wait for listening state
        while True:
            msg = json.loads(await ws.recv())
            print(f"<- [INIT] {msg}")
            if msg.get("type") == "state" and msg.get("state") == "listening":
                print("Agent is ready and listening!\n" + "="*60)
                break

        for title, question in TEST_QUESTIONS:
            print(f"\n--- Testing: {title} ---")
            print(f"Spoken text: \"{question}\"")
            
            t0 = time.perf_counter()
            await ws.send(json.dumps({
                "type": "user_transcript",
                "text": question,
                "language": "hinglish"
            }))
            
            ai_text_received = False
            audio_received = False
            audio_bytes_total = 0
            audio_format = ""
            
            while True:
                raw = await ws.recv()
                msg = json.loads(raw)
                
                if msg.get("type") == "ai_text":
                    ai_text_received = True
                    ai_t = time.perf_counter() - t0
                    print(f"<- [AI_TEXT] ({ai_t:.2f}s latency):")
                    print(f"   {msg.get('text')}")
                    print(f"   User message received by AI: {msg.get('user_message')}")
                    
                elif msg.get("type") == "ai_audio_mp3":
                    audio_received = True
                    audio_format = "MP3 (Neural High-Fidelity)"
                    audio_len = len(msg.get("audio_base64", ""))
                    audio_bytes_total += audio_len
                    print(f"<- [AI_AUDIO_MP3] Speaker: {msg.get('speaker')} (base64 length: {audio_len})")
                    
                elif msg.get("type") == "ai_audio_pcm":
                    audio_received = True
                    audio_format = "PCM Chunks"
                    audio_bytes_total += len(msg.get("audio_base64", ""))
                    
                elif msg.get("type") == "ai_audio_pcm_done":
                    done_t = time.perf_counter() - t0
                    print(f"<- [AUDIO_STREAM_DONE] Total turn time: {done_t:.2f}s | Audio format: {audio_format} | Total bytes: {audio_bytes_total}")
                    
                elif msg.get("type") == "state" and msg.get("state") == "listening":
                    print(f"Turn finished successfully, agent ready for next turn.\n" + "-"*60)
                    break
                    
                elif msg.get("type") == "state" and msg.get("state") == "error":
                    print(f"❌ [ERROR] {msg.get('message')}")
                    break

if __name__ == "__main__":
    asyncio.run(run_voice_test())
