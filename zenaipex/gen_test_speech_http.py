import requests
import base64
import json

response = requests.post(
    "http://127.0.0.1:8002/api/v1/companies/668ec092789ffab2f25b2931/agents/672728271101929944bb9545/speak",
    json={"text": "Hello, this is a voice recognition test."},
    headers={"Content-Type": "application/json"}
)

if response.status_code == 200:
    data = response.json()
    if "audio_base64" in data:
        with open("test_speech.mp3", "wb") as f:
            f.write(base64.b64decode(data["audio_base64"]))
        print("Successfully generated test_speech.mp3")
    else:
        print("No audio_base64 in response")
else:
    print(f"Failed with {response.status_code}: {response.text}")
