import asyncio
import os
import sys

sys.path.insert(0, os.getcwd())
from core.config import settings
from twilio.rest import Client

def main():
    try:
        print(f"Checking Twilio Account SID: {settings.twilio_account_sid}")
        client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
        numbers = client.incoming_phone_numbers.list(limit=20)
        if not numbers:
            print("No phone numbers found in this Twilio account!")
        for n in numbers:
            print(f"Phone Number: {n.phone_number}, SID: {n.sid}, Friendly Name: {n.friendly_name}")
            
        print("\nChecking Verified Caller IDs...")
        verified = client.outgoing_caller_ids.list(limit=20)
        for v in verified:
            print(f"Verified Number: {v.phone_number}, Name: {v.friendly_name}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
