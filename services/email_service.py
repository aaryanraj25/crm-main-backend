# services/email_service.py
import smtplib
from email.message import EmailMessage
import os
from dotenv import load_dotenv
import logging
import asyncio

logger = logging.getLogger(__name__)
load_dotenv()

SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))

async def send_email(to_email: str, subject: str, content: str) -> bool:
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = SENDER_EMAIL
        msg["To"] = to_email
        msg.set_content(content)

        # smtplib.SMTP is synchronous — use regular `with`, not `async with`
        def sync_send():
            with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
                server.starttls()
                server.login(SENDER_EMAIL, SENDER_PASSWORD)
                server.send_message(msg)
                logger.info(f"Email sent successfully to {to_email}")

        await asyncio.to_thread(sync_send)  # Run blocking code in a thread
        return True
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return False


async def send_verification_email(to_email: str, name: str) -> bool:
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
    subject = f"Welcome to {organization}"
    content = f"""
    Hello {name},
    
    You have been added as an employee at {organization}.
    Please set your password to access the system.
    
    Regards,
    {organization} Team
    """
    return await send_email(to_email, subject, content)

async def send_admin_invitation(to_email: str, name: str, organization: str) -> bool:
    subject = f"Admin Access for {organization}"
    content = f"""
    Hello {name},
    
    You have been granted admin access for {organization}.
    Please set your password to access the admin dashboard.
    
    Regards,
    {organization} Team
    """
    return await send_email(to_email, subject, content)

async def send_admin_otp_email(to_email: str, name: str, otp: str) -> bool:
    subject = f"OTP for Admin Access"
    content = f"""
    Hi {name},

    You’ve requested to verify your identity.

    Your One-Time Password (OTP) is: **{otp}**

    This OTP is valid for the next 10 minutes. Please do not share it with anyone.

    If you didn’t request this, please ignore this email or contact support.

    Best regards,  
    CRM Team
    """
    return await send_email(to_email, subject, content)
