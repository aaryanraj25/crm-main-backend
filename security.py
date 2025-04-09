# security.py
from fastapi import HTTPException, Security, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
import os
from database import get_database, admins_collection, employee_collection
from datetime import datetime, timedelta

security = HTTPBearer()

# Environment variables
SECRET_KEY = os.getenv("SECRET_KEY", "y0f9ec959fc1a0bdadeb3546f9e634dda5914847dfddfee954688b9352f3c5f0e")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

def create_access_token(data: dict):
    """Create a new access token"""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def decode_token(token: str) -> dict:
    """Decode and verify a token"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

def get_current_superadmin(
    credentials: HTTPAuthorizationCredentials = Security(security)
):
    """Verify and return superadmin credentials"""
    try:
        payload = decode_token(credentials.credentials)
        if payload.get("role") != "superadmin":
            raise HTTPException(
                status_code=403, 
                detail="Not authorized as SuperAdmin"
            )
        return payload
    except Exception as e:
        raise HTTPException(
            status_code=401,
            detail=str(e)
        )

def get_current_admin(
    credentials: HTTPAuthorizationCredentials = Security(security)
):
    """Verify and return admin credentials"""
    try:
        payload = decode_token(credentials.credentials)
        
        # Debug log
        print("Admin Token Payload:", payload)
        
        if payload.get("role") != "admin":
            raise HTTPException(
                status_code=403,
                detail="Not authorized as Admin"
            )
        
        required_fields = ["admin_id", "organization_id", "email"]
        for field in required_fields:
            if not payload.get(field):
                raise HTTPException(
                    status_code=401,
                    detail=f"Invalid token: missing {field}"
                )
                
        return payload
    except Exception as e:
        raise HTTPException(
            status_code=401,
            detail=str(e)
        )

def get_current_employee(
    credentials: HTTPAuthorizationCredentials = Security(security)
):
    """Verify and return employee credentials"""
    try:
        payload = decode_token(credentials.credentials)
        
        # Debug log
        print("Employee Token Payload:", payload)
        
        if payload.get("role") != "employee":
            raise HTTPException(
                status_code=403,
                detail="Not authorized as Employee"
            )
            
        required_fields = ["employee_id", "organization_id", "email"]
        for field in required_fields:
            if not payload.get(field):
                raise HTTPException(
                    status_code=401,
                    detail=f"Invalid token: missing {field}"
                )
        
        return payload
    except Exception as e:
        raise HTTPException(
            status_code=401,
            detail=str(e)
        )

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(security),
    db = Depends(get_database)
):
    """Get current user details (admin or employee)"""
    try:
        payload = decode_token(credentials.credentials)
        role = payload.get("role")

        if role not in ["admin", "employee"]:
            raise HTTPException(
                status_code=403,
                detail="Unauthorized role"
            )

        # Determine collection and ID based on role
        if role == "admin":
            user_id = payload.get("admin_id")
            collection = admins_collection
        else:  # employee
            user_id = payload.get("employee_id")
            collection = employee_collection

        if not user_id:
            raise HTTPException(
                status_code=401,
                detail="Invalid token: missing user ID"
            )

        # Find user
        user = await collection.find_one({"_id": user_id})
        if not user:
            raise HTTPException(
                status_code=404,
                detail="User not found"
            )

        # Prepare user data
        user_data = {
            "user_id": user_id,
            "email": user.get("email"),
            "name": user.get("name"),
            "role": role,
            "organization_id": payload.get("organization_id"),
            "organization": payload.get("organization"),
            "created_at": user.get("created_at"),
            "is_active": user.get("is_active", True)
        }

        # Add role-specific data
        if role == "admin":
            user_data.update({
                "emp_count": payload.get("emp_count", 0),
                "is_verified": user.get("is_verified", False)
            })
        else:  # employee
            user_data.update({
                "admin_id": payload.get("admin_id"),
                "designation": user.get("designation"),
                "department": user.get("department")
            })

        return user_data

    except Exception as e:
        raise HTTPException(
            status_code=401,
            detail=f"Authentication error: {str(e)}"
        )

def create_admin_token(admin_data: dict) -> str:
    """Create token for admin"""
    token_data = {
        "role": "admin",
        "admin_id": admin_data["_id"],
        "email": admin_data["email"],
        "organization_id": admin_data.get("organization_id"),
        "organization": admin_data.get("organization"),
        "emp_count": admin_data.get("emp_count", 0)
    }
    return create_access_token(token_data)

def create_employee_token(employee_data: dict) -> str:
    """Create token for employee"""
    token_data = {
        "role": "employee",
        "employee_id": employee_data["_id"],
        "email": employee_data["email"],
        "organization_id": employee_data.get("organization_id"),
        "organization": employee_data.get("organization"),
        "admin_id": employee_data.get("admin_id")
    }
    return create_access_token(token_data)

def create_superadmin_token() -> str:
    """Create token for superadmin"""
    token_data = {
        "role": "superadmin",
        "superadmin_id": "SUPER-ADMIN",
        "email": os.getenv("SUPER_ADMIN_EMAIL")
    }
    return create_access_token(token_data)