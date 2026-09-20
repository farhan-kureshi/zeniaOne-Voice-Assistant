"""
Setup Script for AI Voice Call Agent
Helps initialize the project and verify configuration.
"""
import sys
import os
from pathlib import Path

def check_python_version():
    """Check if Python version is 3.10+"""
    version = sys.version_info
    if version.major < 3 or (version.major == 3 and version.minor < 10):
        print("❌ Python 3.10+ required")
        print(f"   Current version: {version.major}.{version.minor}.{version.micro}")
        return False
    print(f"✓ Python version: {version.major}.{version.minor}.{version.micro}")
    return True


def check_env_file():
    """Check if .env file exists"""
    if not Path(".env").exists():
        print("❌ .env file not found")
        print("   Copy .env.example to .env and fill in your credentials:")
        print("   cp .env.example .env")
        return False
    print("✓ .env file exists")
    return True


def check_dependencies():
    """Check if key dependencies are installed"""
    required_modules = [
        "fastapi",
        "twilio",
        "pymongo",
        "pinecone",
        "requests",
        "sentence_transformers"
    ]
    
    missing = []
    for module in required_modules:
        try:
            __import__(module)
            print(f"✓ {module} installed")
        except ImportError:
            print(f"❌ {module} not found")
            missing.append(module)
    
    if missing:
        print("\n   Run: uv sync")
        return False
    
    return True


def check_config():
    """Check if critical config values are set"""
    try:
        import config
        
        required_configs = [
            "TWILIO_ACCOUNT_SID",
            "TWILIO_AUTH_TOKEN",
            "MONGODB_URI",
            "NGROK_URL"
        ]
        
        missing = []
        for cfg in required_configs:
            value = getattr(config, cfg, None)
            if not value or value == "":
                print(f"❌ {cfg} not configured")
                missing.append(cfg)
            else:
                # Mask sensitive values
                if "KEY" in cfg or "TOKEN" in cfg or "URI" in cfg:
                    display = value[:10] + "..." if len(value) > 10 else "***"
                else:
                    display = value
                print(f"✓ {cfg}: {display}")
        
        if missing:
            print(f"\n   Set these in .env file: {', '.join(missing)}")
            return False
        
        return True
        
    except ImportError:
        print("❌ Could not import config.py")
        return False


def check_static_dir():
    """Check if static directory exists"""
    static_dir = Path("./static")
    if not static_dir.exists():
        print("⚠ Creating static directory...")
        static_dir.mkdir()
        print("✓ Static directory created")
    else:
        print("✓ Static directory exists")
    
    # Check for audio files
    required_files = ["response.mp3", "incomming_alert.mp3"]
    for file in required_files:
        file_path = static_dir / file
        if not file_path.exists():
            print(f"⚠ Missing audio file: {file}")
            print("   You'll need to add these files manually")
    
    return True


def test_mongodb():
    """Test MongoDB connection"""
    try:
        from modules.mongodb import client
        client.server_info()
        print("✓ MongoDB connection successful")
        return True
    except Exception as e:
        print(f"❌ MongoDB connection failed: {e}")
        print("   Check MONGODB_URI in .env")
        return False


def test_pinecone():
    """Test Pinecone connection"""
    try:
        import config
        if not config.PINECONE_API_KEY:
            print("⚠ PINECONE_API_KEY not set (optional for initial testing)")
            return True
        
        from modules.vector_store import get_vector_store
        vs = get_vector_store()
        stats = vs.get_index_stats()
        print(f"✓ Pinecone connected - {stats.get('total_vector_count', 0)} vectors")
        return True
    except Exception as e:
        print(f"⚠ Pinecone connection failed: {e}")
        print("   This is optional - set PINECONE_API_KEY when ready")
        return True  # Non-critical


def initialize_mongodb():
    """Initialize MongoDB indexes"""
    try:
        from modules.mongodb import init_mongodb
        init_mongodb()
        print("✓ MongoDB indexes created")
        return True
    except Exception as e:
        print(f"❌ Failed to create MongoDB indexes: {e}")
        return False


def main():
    """Run all setup checks"""
    print("=" * 60)
    print("AI Voice Call Agent - Setup Check")
    print("=" * 60)
    print()
    
    checks = [
        ("Python Version", check_python_version),
        ("Environment File", check_env_file),
        ("Dependencies", check_dependencies),
        ("Configuration", check_config),
        ("Static Directory", check_static_dir),
        ("MongoDB Connection", test_mongodb),
        ("MongoDB Initialization", initialize_mongodb),
        ("Pinecone Connection", test_pinecone),
    ]
    
    results = []
    for name, check_func in checks:
        print(f"\n[{name}]")
        result = check_func()
        results.append((name, result))
        print()
    
    print("=" * 60)
    print("Setup Summary")
    print("=" * 60)
    
    all_passed = True
    for name, result in results:
        status = "✓" if result else "❌"
        print(f"{status} {name}")
        if not result:
            all_passed = False
    
    print()
    
    if all_passed:
        print("🎉 Setup complete! You're ready to run the application.")
        print()
        print("Next steps:")
        print("1. Start ngrok: ngrok http 7000")
        print("2. Update NGROK_URL in .env with your ngrok URL")
        print("3. Run the app: uv run python app.py")
        print("4. Configure Twilio webhooks in Twilio console")
        print("5. (Optional) Seed Pinecone: uv run python seed_knowledge.py")
    else:
        print("⚠️  Setup incomplete. Please fix the issues above.")
        print()
        print("Common fixes:")
        print("- Install dependencies: uv sync")
        print("- Copy and configure .env: cp .env.example .env")
        print("- Start MongoDB: mongod")
        print("- Check your API keys are correct")
    
    print()
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
