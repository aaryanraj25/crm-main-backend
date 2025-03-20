import os
from passlib.context import CryptContext
from datetime import datetime, timedelta, timezone
import jwt

SECRET_KEY = "y0f9ec959fc1a0bdadeb3546f9e634dda5914847dfddfee954688b9352f3c5f0e"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Super Admin Credentials
SUPERADMIN_EMAIL = os.getenv("SUPERADMIN_EMAIL")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data:dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta( minutes = ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm = ALGORITHM)
