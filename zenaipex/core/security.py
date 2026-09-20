"""
Zenaipex AI — Security utilities.

JWT token creation/verification, password hashing, and encryption
of sensitive tenant credentials stored in the database.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional, Any, Dict
from jose import JWTError, jwt
from passlib.context import CryptContext
from cryptography.fernet import Fernet
import base64
import logging

from core.config import settings

logger = logging.getLogger(__name__)

# ── Password Hashing ──────────────────────────────────────────────────────────

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """Return bcrypt hash of a plain-text password."""
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plain password against its bcrypt hash."""
    return pwd_context.verify(plain, hashed)


# ── JWT Tokens ────────────────────────────────────────────────────────────────

def create_access_token(
    data: Dict[str, Any],
    expires_delta: Optional[timedelta] = None,
) -> str:
    """
    Create a signed JWT access token.

    Args:
        data:          Payload dict — must include "sub" (user_id string)
        expires_delta: Custom expiry (defaults to config setting)

    Returns:
        Signed JWT string
    """
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.jwt_access_token_expire_minutes)
    )
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.app_secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token(user_id: str) -> str:
    """
    Create a long-lived JWT refresh token.

    Args:
        user_id: String representation of the user's MongoDB _id

    Returns:
        Signed JWT refresh token
    """
    expire = datetime.now(timezone.utc) + timedelta(days=settings.jwt_refresh_token_expire_days)
    payload = {"sub": user_id, "exp": expire, "type": "refresh"}
    return jwt.encode(payload, settings.app_secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Decode and verify a JWT token.

    Returns:
        Payload dict on success, None on any failure.
    """
    try:
        payload = jwt.decode(
            token,
            settings.app_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        return payload
    except JWTError as exc:
        logger.debug(f"JWT decode failed: {exc}")
        return None


def decode_access_token(token: str) -> Optional[str]:
    """
    Decode an access token and return the user_id ("sub" claim).

    Returns:
        user_id string, or None if invalid/expired/wrong type.
    """
    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        return None
    return payload.get("sub")


def decode_refresh_token(token: str) -> Optional[str]:
    """
    Decode a refresh token and return the user_id.

    Returns:
        user_id string, or None if invalid/expired/wrong type.
    """
    payload = decode_token(token)
    if not payload or payload.get("type") != "refresh":
        return None
    return payload.get("sub")


# ── Field-Level Encryption ────────────────────────────────────────────────────
# Used to store tenant Twilio credentials and API keys in MongoDB securely.

def _get_fernet() -> Optional[Fernet]:
    """Return Fernet instance using ENCRYPTION_KEY from settings."""
    if not settings.encryption_key:
        if settings.is_production:
            logger.error("❌ ENCRYPTION_KEY not set in production!")
            raise ValueError("ENCRYPTION_KEY must be set in production for field-level encryption.")
        logger.warning("ENCRYPTION_KEY not set — field encryption disabled")
        return None
    try:
        key = settings.encryption_key.encode()
        # Accept raw Fernet key or base64-url encoded key
        return Fernet(key)
    except Exception:
        try:
            key = base64.urlsafe_b64decode(settings.encryption_key + "==")
            return Fernet(base64.urlsafe_b64encode(key))
        except Exception as exc:
            logger.error(f"Invalid ENCRYPTION_KEY: {exc}")
            return None


def encrypt_secret(value: str) -> str:
    """
    Encrypt a sensitive string (Twilio token, API key) for DB storage.

    Returns:
        Encrypted string (base64 encoded), or the original value if
        encryption is disabled (for dev environments).
    """
    if not value:
        return value
    fernet = _get_fernet()
    if not fernet:
        return value  # dev fallback — do NOT use in production
    return fernet.encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    """
    Decrypt a previously encrypted string from the DB.

    Returns:
        Decrypted plain-text string, or original value on failure.
    """
    if not value:
        return value
    fernet = _get_fernet()
    if not fernet:
        return value  # dev fallback
    try:
        # Fernet tokens start with gAAAAA
        if not value.startswith("gAAAAA"):
            # It's an unencrypted plain-text key from before encryption was enabled
            return value
        return fernet.decrypt(value.encode()).decode()
    except Exception as exc:
        logger.warning(f"Failed to decrypt secret (corrupted token). Using fallback.")
        return value


# ── Email Verification Tokens ─────────────────────────────────────────────────

def create_email_verification_token(email: str) -> str:
    """Create a short-lived token for email address verification."""
    expire = datetime.now(timezone.utc) + timedelta(hours=24)
    payload = {"sub": email, "exp": expire, "type": "email_verify"}
    return jwt.encode(payload, settings.app_secret_key, algorithm=settings.jwt_algorithm)


def verify_email_token(token: str) -> Optional[str]:
    """Return email address from valid email verification token, else None."""
    payload = decode_token(token)
    if not payload or payload.get("type") != "email_verify":
        return None
    return payload.get("sub")


def create_password_reset_token(user_id: str) -> str:
    """Create a short-lived token for password reset."""
    expire = datetime.now(timezone.utc) + timedelta(hours=1)
    payload = {"sub": user_id, "exp": expire, "type": "pw_reset"}
    return jwt.encode(payload, settings.app_secret_key, algorithm=settings.jwt_algorithm)


def verify_password_reset_token(token: str) -> Optional[str]:
    """Return user_id from valid password reset token, else None."""
    payload = decode_token(token)
    if not payload or payload.get("type") != "pw_reset":
        return None
    return payload.get("sub")
