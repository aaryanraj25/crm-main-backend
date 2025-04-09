from fastapi import APIRouter, HTTPException, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from models.admin import AdminModel, SetPasswordRequest
from database import get_database, admins_collection, organization_collection
import logging
from dependencies import verify_password, hash_password, create_access_token
from bson import ObjectId
from datetime import datetime, timezone
from services.email_service import send_verification_email
from utils import generate_random_id, generate_admin_id, generate_organization_id

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
    existing_admin = await admins_collection.find_one({"email": admin.email})
    if existing_admin:
        raise HTTPException(status_code=400, detail="Admin with this email already exists")

    # Generate custom string ID
    organization_id = generate_organization_id()

    organization_data = {
        "_id": organization_id,  # 👈 Set custom string ID here
        "name": admin.organization,
        "address": admin.address,
        "contact_person": admin.name,
        "contact_email": admin.email,
        "contact_number": admin.phone,
        "total_employees": admin.emp_count
    }

    await organization_collection.insert_one(organization_data)

    admin_id = generate_admin_id()

    admin_data = {
        "_id": admin_id,  # 👈 Custom string ID for admin
        "email": admin.email,
        "name": admin.name,
        "phone": admin.phone,
        "organization_id": organization_id,
        "organization": admin.organization,
        "address": admin.address,
        "emp_count": admin.emp_count,
        "is_verified": False,
        "role": "admin",
        "created_at": datetime.now(timezone.utc)
    }

    await admins_collection.insert_one(admin_data)

    await send_verification_email(admin.email, admin.name)

    return {
        "message": "Registration successful. Your request has been sent for verification.",
        "admin_id": admin_id,
        "organization_id": organization_id,
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
    organizations_collection = db["organization"]

    # Find admin by email
    admin = await admins_collection.find_one({"email": email})
    if not admin:
        raise HTTPException(status_code=404, detail="Admin not found")

    # Check if admin is verified
    if not admin.get("is_verified", False):
        raise HTTPException(status_code=403, detail="Admin is not verified yet")

    # Validate password
    if not verify_password(password, admin.get("password")):
        raise HTTPException(status_code=401, detail="Invalid password")

    # Fetch organization using string-based ID
    organization = await organization_collection.find_one(
        {"_id": admin["organization_id"]}
    )
    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")

    # Prepare admin details
    admin_details = {
        "id": admin.get("_id"),  # Assuming you store admin_id during registration
        "name": admin.get("name", ""),
        "email": admin["email"],
        "role": "admin",
    }

    # Prepare organization details
    organization_details = {
        "id": organization.get("_id"),
        "name": organization.get("name"),
    }

    # Generate access token
    token = create_access_token({
        "admin_id": admin.get("_id"),
        "role": "admin",
        "organization_id": admin.get("organization_id"),
        "organization_name": admin.get("organization")
    })

    # Update last login time
    await admins_collection.update_one(
        {"email": email},
        {"$set": {"last_login": datetime.utcnow()}}
    )

    return {
        "success": True,
        "message": "Login successful",
        "token": token,
        "user": admin_details,
        "organization": organization_details
    }