# 📞 Call Trigger - Test System

Tools to trigger outbound test calls from RK Hospital AI system to your phone.

---

## 🎯 Quick Start

### Prerequisites
Make sure these are running first:

**Terminal 1** - ngrok:
```bash
D:\tools\ngrok\ngrok.exe http 5000
```

**Terminal 2** - FastAPI:
```bash
cd "D:\Projects\Spinabot\AI Voice Call Agent"
.venv\Scripts\Activate.ps1
python app.py
```

**Terminal 3** - Update Twilio webhook:
- Copy ngrok URL from Terminal 1
- Go to: https://console.twilio.com/us1/develop/phone-numbers/manage/incoming
- Update webhook URL to: `https://YOUR-NGROK-URL/voice`

---

## 🌐 Method 1: Web Interface (Easiest)

1. Open `test_call.html` in your browser
2. Enter your phone number (with country code)
3. Click "📞 Call Me Now"
4. Answer your phone!

**Features:**
- ✅ Beautiful UI
- ✅ Real-time status updates
- ✅ Input validation
- ✅ Example phone formats
- ✅ Error messages with troubleshooting

---

## 💻 Method 2: Python Script

### Basic Usage
```bash
python trigger_call.py
```
Uses default number: `+919944559392`

### Custom Number
```bash
python trigger_call.py +919876543210
```

**Features:**
- ✅ Command-line interface
- ✅ Detailed error messages
- ✅ Troubleshooting tips
- ✅ Exit codes for automation

---

## 🔧 Method 3: Direct API Call

### Browser
```
http://localhost:5000/make_call?phone_number=+919944559392
```

### PowerShell
```powershell
curl -X POST "http://localhost:5000/make_call?phone_number=%2B919944559392"
```

### Python
```python
import requests
response = requests.post("http://localhost:5000/make_call?phone_number=+919944559392")
print(response.json())
```

---

## 📱 Phone Number Format

**Must include country code:**

| Country | Format | Example |
|---------|--------|---------|
| 🇮🇳 India | +91XXXXXXXXXX | +919944559392 |
| 🇺🇸 USA | +1XXXXXXXXXX | +12025551234 |
| 🇬🇧 UK | +44XXXXXXXXXX | +447911123456 |
| 🇦🇺 Australia | +61XXXXXXXXX | +61412345678 |
| 🇨🇦 Canada | +1XXXXXXXXXX | +14165551234 |

---

## 🎯 What Happens During Call

1. **Your phone rings** (5-10 seconds after trigger)
2. **Answer the call**
3. **AI greets you:** "Welcome to RK Hospital..."
4. **Conversation flow:**
   - AI asks for your name
   - AI asks which doctor you need
   - AI asks for appointment date/time
   - AI asks for phone number
   - AI asks for reason for visit
   - AI confirms all details
5. **Say "goodbye" or "thank you"**
6. **Appointment saved** to MongoDB + Google Sheets

---

## ⚠️ Troubleshooting

### "Connection Error"
**Problem:** Can't connect to localhost:5000

**Solution:**
```bash
# Check if FastAPI is running
curl http://localhost:5000

# If not, start it:
cd "D:\Projects\Spinabot\AI Voice Call Agent"
python app.py
```

---

### "Call not connecting"
**Problem:** Phone doesn't ring

**Checklist:**
- [ ] ngrok is running (Terminal 1)
- [ ] FastAPI is running (Terminal 2)
- [ ] Twilio webhook updated with ngrok URL
- [ ] Phone number has correct format (+country_code)
- [ ] Twilio account has credits for outbound calls

---

### "No audio during call"
**Problem:** Call connects but can't hear AI

**Solution:**
- Check Sarvam API key in `.env`
- Check FastAPI logs for TTS errors
- Verify ngrok URL is correct in Twilio webhook

---

### "Invalid phone number"
**Problem:** Error about phone format

**Solution:**
- Must start with `+`
- Must include country code
- No spaces or dashes
- Example: `+919944559392` ✅ not `9944559392` ❌

---

## 💡 Tips

1. **Use HTML interface** for easiest experience
2. **Check terminal logs** while testing
3. **Twilio charges apply** for outbound calls (check balance)
4. **International calls** may cost more than domestic
5. **Test with your own number** first before calling patients

---

## 📊 Cost Estimates (Approximate)

| Call Type | Cost per Minute |
|-----------|----------------|
| India → India | ~₹1-2 |
| USA → India | ~$0.02-0.04 |
| India → USA | ~₹3-5 |

Check your Twilio console for exact rates.

---

## 🔗 Useful Links

- [Twilio Console](https://console.twilio.com)
- [Check Twilio Balance](https://console.twilio.com/us1/billing/manage-billing)
- [View Call Logs](https://console.twilio.com/us1/monitor/logs/calls)

---

**Happy Testing!** 🎉
