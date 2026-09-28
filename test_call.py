import os
from twilio.rest import Client

account_sid = "YOUR_TWILIO_SID"
auth_token = "YOUR_TWILIO_TOKEN"
client = Client(account_sid, auth_token)

# This will ring your Indian mobile number
to_number = "+918799046710" 
from_number = "+19144443927"

print(f"Dialing {to_number} from {from_number}...")

try:
    call = client.calls.create(
        to=to_number,
        from_=from_number,
        url="https://clean-signs-melt.loca.lt/api/v1/webhook/twilio/advanced/voice"
    )
    print(f"Call initiated successfully! Call SID: {call.sid}")
    print("Please pick up your phone when it rings. Incoming calls are FREE!")
except Exception as e:
    print(f"Error making call: {e}")
