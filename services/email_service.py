import smtplib
from email.message import EmailMessage
import os
from dotenv import load_dotenv
import logging
from typing import Optional
import asyncio

# Configure logging
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.hostinger.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))

async def send_email(to_email: str, subject: str, content: str) -> bool:
    """Generic email sending function"""
    try:
        # Run SMTP operations in a thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _send_email_sync, to_email, subject, content)
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return False

def _send_email_sync(to_email: str, subject: str, content: str) -> bool:
    """Synchronous email sending function to run in thread pool"""
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = SENDER_EMAIL
        msg["To"] = to_email
        msg.set_content(content)

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.send_message(msg)
            logger.info(f"Email sent successfully to {to_email}")
            return True
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return False

async def send_verification_email(to_email: str, name: str) -> bool:
    """Send verification email to newly registered admin"""
    subject = "Admin Registration Pending Verification"
    content = f"""
    Hello {name},

    Your registration request has been forwarded for verification.
    The Super Admin will review your request and approve it shortly.

    Regards,
    CRM Team
    """
    return await send_email(to_email, subject, content)

async def send_approval_email(to_email: str, name: str) -> bool:
    """Send approval notification to admin"""
    subject = "Admin Registration Approved"
    content = f"""
    Hello {name},

    Your registration has been approved. You can now set your password and log in.
    Please use the following link to set your password:
    [Your application URL]/set-password

    Regards,
    CRM Team
    """
    return await send_email(to_email, subject, content)

async def send_employee_invitation(to_email: str, name: str, organization: str) -> bool:
    """Send invitation email to new employee"""
    subject = f"Welcome to {organization}"
    content = f"""
    Hello {name},

    You have been added as an employee at {organization}.
    Please set your password to access the system.

    Regards,
    {organization} Team
    """
    return await send_email(to_email, subject, content)