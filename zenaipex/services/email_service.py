import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import logging
import asyncio
from typing import Optional

from core.config import settings

logger = logging.getLogger(__name__)

async def send_email(to_email: str, subject: str, body_text: str, body_html: Optional[str] = None) -> bool:
    """Send an email using configured SMTP settings."""
    if not settings.smtp_host:
        logger.warning(f"SMTP not configured. Would have sent email to {to_email}: {subject}")
        # Return False to let the user know email sending is not configured
        raise RuntimeError("SMTP email is not configured on the server.")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.from_email
    msg["To"] = to_email

    part1 = MIMEText(body_text, "plain")
    msg.attach(part1)

    if body_html:
        part2 = MIMEText(body_html, "html")
        msg.attach(part2)

    def _send():
        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
                if settings.smtp_port == 587:
                    server.starttls()
                if settings.smtp_user and settings.smtp_password:
                    server.login(settings.smtp_user, settings.smtp_password)
                server.send_message(msg)
            return True
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {e}")
            raise RuntimeError(f"Email delivery failed: {str(e)}")

    return await asyncio.to_thread(_send)

async def send_verification_email(email: str, token: str):
    """Send the email verification link to the user."""
    # Assuming frontend route is /verify-email?token=...
    verify_url = f"{settings.frontend_url}/verify-email?token={token}"
    
    subject = "Verify your Zenaipex AI account"
    body_text = f"Welcome to Zenaipex AI!\n\nPlease verify your email by clicking this link:\n{verify_url}"
    body_html = f"""
    <html>
      <body>
        <p>Welcome to Zenaipex AI!</p>
        <p>Please verify your email by clicking the link below:</p>
        <p><a href="{verify_url}">Verify Email</a></p>
        <p>Or paste this link into your browser: <br>{verify_url}</p>
      </body>
    </html>
    """
    
    # We always log it for dev environments
    logger.info(f"Verification Link for {email}: {verify_url}")
    
    # Try sending if configured
    if settings.smtp_host:
        await send_email(email, subject, body_text, body_html)
