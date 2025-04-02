from fastapi import  HTTPException, Security, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
import os
from database import get_database
from bson import ObjectId



security = HTTPBearer()


SECRET_KEY = os.getenv("SECRET KEY", "y0f9ec959fc1a0bdadeb3546f9e634dda5914847dfddfee954688b9352f3c5f0e")
ALGORITHM = "HS256"

def convert_objectid_to_str(document):
    """Recursively converts ObjectId fields in a document to strings."""
    if isinstance(document, dict):
        for key, value in document.items():
            if isinstance(value, ObjectId):
                document[key] = str(value)
            elif isinstance(value, list):  
                document[key] = [str(v) if isinstance(v, ObjectId) else v for v in value]
    return document


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
        
async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(security),
    db=Depends(get_database)
):
    """Extract and verify the current user (Admin or Employee) from JWT token."""
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        role = payload.get("role")

        if role == "admin":
            user_id = payload.get("admin_id")
            collection = db.admin_collection
        elif role == "employee":
            user_id = payload.get("employee_id")
            collection = db.employee_collection
        else:
            raise HTTPException(status_code=403, detail="Unauthorized role")

        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")

        user = await collection.find_one({"_id": ObjectId(user_id)})
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Convert ObjectId fields to strings
        user["user_id"] = str(user["_id"])
        user["organization_id"] = payload.get("organization_id", "")
        user["organization"] = payload.get("organization", "")
        if role == "admin":
            user["emp_count"] = payload.get("emp_count", 0)
        elif role == "employee":
            user["admin_id"] = payload.get("admin_id", "")

        return {**user, "role": role}

    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")        