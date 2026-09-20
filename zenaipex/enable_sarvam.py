import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

async def main():
    client = AsyncIOMotorClient('mongodb://localhost:27017/')
    db = client['zenaipex']
    
    # Check current Sarvam
    sarvam = await db['ai_providers'].find_one({"provider": "sarvam"})
    if not sarvam:
        print("Sarvam provider not found.")
        return
        
    print(f"Before - Enabled: {sarvam.get('enabled')}, Priority: {sarvam.get('priority')}, Model: {sarvam.get('model')}")
    
    # We want Sarvam to have highest priority. Let's make it priority 0.
    await db['ai_providers'].update_one(
        {"provider": "sarvam"},
        {"$set": {"enabled": True, "priority": 0}}
    )
    
    sarvam_after = await db['ai_providers'].find_one({"provider": "sarvam"})
    print(f"After - Enabled: {sarvam_after.get('enabled')}, Priority: {sarvam_after.get('priority')}")
    
asyncio.run(main())
