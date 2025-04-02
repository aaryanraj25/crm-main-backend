from fastapi import APIRouter, HTTPException, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from models.admin import AdminModel, SetPasswordRequest
from database import get_database, admins_collection, organization_collection
import logging
from dependencies import verify_password, hash_password, create_access_token
from bson import ObjectId
from datetime import datetime, timezone
from services.email_service import send_verification_email


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


router = APIRouter()

def convert_objectid_to_str(document):
    """Recursively converts ObjectId fields in a document to strings."""
    if isinstance(document, dict):
        for key, value in document.items():
            if isinstance(value, ObjectId):
                document[key] = str(value)
            elif isinstance(value, list):  
                document[key] = [str(v) if isinstance(v, ObjectId) else v for v in value]
    return document

@router.post("/register")
async def register_admin(
    admin: AdminModel,
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    # Check if an admin with the same email exists
    existing_admin = await admins_collection.find_one({"email": admin.email})
    if existing_admin:
        raise HTTPException(status_code=400, detail="Admin with this email already exists")

    # Create organization entry
    organization_data = {
        "name": admin.organization,
        "address": admin.address,
        "contact_person": admin.name,
        "contact_email": admin.email,
        "contact_number": admin.phone,
        "total_employees": admin.emp_count  # Initial employee count
    }

    # Insert organization into the database
    organization_result = await organization_collection.insert_one(organization_data)

    if not organization_result.inserted_id:
        raise HTTPException(status_code=500, detail="Failed to create organization")

    organization_id = organization_result.inserted_id  # ✅ Use actual inserted ObjectId

    # Store admin details in `admins_collection`
    admin_data = {
        "email": admin.email,
        "name": admin.name,
        "phone": admin.phone,
        "organization_id": str(organization_id),  # ✅ Convert to string for consistency
        "organization": admin.organization,
        "address": admin.address,
        "emp_count": admin.emp_count,
        "is_verified": False,
        "role": "admin",
        "created_at": datetime.now(timezone.utc)
    }

    admin_result = await admins_collection.insert_one(admin_data)

    if not admin_result.inserted_id:
        raise HTTPException(status_code=500, detail="Failed to create admin")

    # Send verification email
    await send_verification_email(admin.email, admin.name)

    return {
        "message": "Registration successful. Your request has been sent for verification.",
        "admin_id": str(admin_result.inserted_id),
        "organization_id": str(organization_id),  # ✅ Ensure it's consistent
        "organization_name": admin.organization
    }


    
@router.post("/set-password")
async def set_admin_password(
    request: SetPasswordRequest,
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    admin = await admins_collection.find_one({"email": request.email})
    
    if not admin:
        raise HTTPException(status_code=404, detail="Admin not found")
    
    if not admin.get("is_verified", False):
        raise HTTPException(status_code=403, detail="Admin not verified")

    # Hash the new password and update in the database
    hashed_password = hash_password(request.password)
    await admins_collection.update_one(
        {"email": request.email},
        {"$set": {"password": hashed_password}}
    )

    return {"message": "Password has been set successfully. You can now log in."}

@router.post("/admin-login")
async def admin_login(email: str, password: str, db=Depends(get_database)):
    admins_collection = db["admin"]

    admin = await admins_collection.find_one({"email": email})
    if not admin:
        raise HTTPException(status_code=404, detail="Admin not found")

    if not admin.get("is_verified", False):
        raise HTTPException(status_code=403, detail="Admin is not verified yet")

    if not verify_password(password, admin.get("password")):
        raise HTTPException(status_code=401, detail="Invalid password")

    token = create_access_token({"admin_id": str(admin["_id"]),  "role": "admin", "organization_id": str(admin["organization_id"]),  
    "organization_name": admin["organization"]})
    
    return {"message": "Login successful", "token": token}    