from fastapi import  HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
import os



security = HTTPBearer()


SECRET_KEY = os.getenv("SECRET KEY", "y0f9ec959fc1a0bdadeb3546f9e634dda5914847dfddfee954688b9352f3c5f0e")
ALGORITHM = "HS256"
def get_current_superadmin(
    credentials: HTTPAuthorizationCredentials = Security(security)):
    
    token = credentials.credentials
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        if payload.get("role") != "superadmin":
            raise HTTPException(status_code=403, detail="Not authorized as SuperAdmin")
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    
    


def get_current_admin(
    credentials: HTTPAuthorizationCredentials = Security(security)):
    
    token = credentials.credentials
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        
        print("Decoded Payload:", payload)  # 🔍 Debugging Step
        
        if payload.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Not authorized as Admin")
        
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    
def get_current_employee( 
    credentials: HTTPAuthorizationCredentials = Security(security)):
    token = credentials.credentials
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        employee_id = payload.get("employee_id")

        if not employee_id:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        return payload  # This will contain employee_id, role, admin_id, etc.
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
        
        