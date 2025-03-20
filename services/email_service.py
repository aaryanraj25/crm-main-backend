import smtplib
from email.message import EmailMessage
import os 
from dotenv import load_dotenv

load_dotenv()

SENDER_EMAIL = os.getenv("SENDER_EMAIL", "meetify.byeplisio@gmail.com")
SENDER_PASSWORD = os.getenv("ENDER_PASSWORD", "ryqhxozkmedcxhho")

def send_verification_email(to_email:str, name:str):
    try:
        msg = EmailMessage()
        msg["Subject"] = "Admin Registration Pending Verification"
        msg["From"] = SENDER_EMAIL
        msg["To"] = to_email
        msg.set_content(f"""
        Hello {name} ,
        
        Your registration request has been forwarded for verification.
        The Super Admin will review your request and approve it shortly.

        Regards,
        CRM Team
                        """)
        
        with smtplib.SMTP("smtp.gmail.com",587 ) as server:
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.send_message(msg)
            
            
    except Exception as e:
        print(f"Failed to send email: {e}")        
