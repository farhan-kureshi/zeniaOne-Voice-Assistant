"""
RK Hospital - Outbound Call Trigger Script
Triggers a test call from the AI system to your phone number.
"""

import requests
import sys
from typing import Optional


def make_call(phone_number: str, api_url: str = "http://localhost:7000") -> bool:
    """
    Trigger an outbound call to the specified phone number.
    
    Args:
        phone_number: Phone number with country code (e.g., +919944559392)
        api_url: Base URL of the FastAPI server
    
    Returns:
        True if call was initiated successfully, False otherwise
    """
    print("=" * 60)
    print("RK Hospital - Test Call System")
    print("=" * 60)
    print()
    
    # Validate phone number
    if not phone_number.startswith('+'):
        print("❌ Error: Phone number must start with + and country code")
        print("   Example: +919944559392 (for India)")
        return False
    
    print(f"📱 Initiating call to: {phone_number}")
    print(f"🌐 API Server: {api_url}")
    print()
    print("⏳ Connecting to server...")
    
    try:
        # Make API request
        response = requests.post(
            f"{api_url}/make_call",
            params={"phone_number": phone_number},
            timeout=10
        )
        
        # Parse response
        data = response.json()
        
        if response.status_code == 200:
            print("✅ SUCCESS! Call initiated.")
            print()
            print("📞 Your phone should ring in 5-10 seconds.")
            print("   Please answer to speak with the AI assistant.")
            print()
            
            if 'call_sid' in data:
                print(f"🆔 Call SID: {data['call_sid']}")
            if 'message' in data:
                print(f"💬 Message: {data['message']}")
            
            print()
            print("=" * 60)
            return True
        else:
            print(f"❌ ERROR: {response.status_code}")
            print()
            print(f"💬 Message: {data.get('error') or data.get('detail', 'Unknown error')}")
            print()
            print("🔧 Troubleshooting:")
            print("   1. Check FastAPI app is running (Terminal 2)")
            print("   2. Check ngrok tunnel is active (Terminal 1)")
            print("   3. Verify phone number format (+country_code + number)")
            print("   4. Check Twilio balance for outbound calls")
            print()
            print("=" * 60)
            return False
            
    except requests.exceptions.ConnectionError:
        print("❌ CONNECTION ERROR")
        print()
        print("Could not connect to FastAPI server.")
        print()
        print("🔧 Make sure:")
        print("   - FastAPI app is running on http://localhost:7000")
        print("   - Run: python realtime_app.py")
        print()
        print("=" * 60)
        return False
        
    except requests.exceptions.Timeout:
        print("❌ TIMEOUT ERROR")
        print()
        print("Server took too long to respond.")
        print()
        print("=" * 60)
        return False
        
    except Exception as e:
        print(f"❌ UNEXPECTED ERROR: {e}")
        print()
        print("=" * 60)
        return False


def main():
    """Main function to run the call trigger."""
    
    # Default phone number (change this to your number)
    DEFAULT_PHONE = "+919944559392"
    
    # Get phone number from command line or use default
    if len(sys.argv) > 1:
        phone_number = sys.argv[1]
    else:
        phone_number = DEFAULT_PHONE
        print()
        print("💡 Tip: You can pass phone number as argument:")
        print(f"   python trigger_call.py +919876543210")
        print()
        print(f"Using default number: {phone_number}")
        print()
    
    # Trigger the call
    success = make_call(phone_number)
    
    # Exit with appropriate code
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
