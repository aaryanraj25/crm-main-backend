# routes/superadmin.py
from fastapi import APIRouter, HTTPException, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from database import get_database, admins_collection
from security import get_current_superadmin
from services.email_service import send_approval_email
from utils import get_current_datetime

router = APIRouter()

@router.get("/pending-admins")
async def get_pending_admins(
    page: int = 1,
    page_size: int = 10,
    db: AsyncIOMotorDatabase = Depends(get_database),
    superadmin: dict = Depends(get_current_superadmin)
):
    """Fetch pending admins with pagination"""
    
    if page < 1 or page_size < 1:
        raise HTTPException(
            status_code=400, 
            detail="Page and page_size must be greater than 0"
        )

    skip = (page - 1) * page_size

    # Query for pending admins
    query = {"is_verified": False}
    
    # Get total count
    total_pending_admins = await admins_collection.count_documents(query)

    # Get paginated results
    pending_admins = await admins_collection.find(query)\
        .sort("created_at", -1)\
        .skip(skip)\
        .limit(page_size)\
        .to_list(length=page_size)

    return {
        "pending_admins": pending_admins,
        "total": total_pending_admins,
        "page": page,
        "page_size": page_size,
        "total_pages": (total_pending_admins + page_size - 1) // page_size
    }

@router.put("/verify-admin/{admin_id}")
async def verify_admin(
    admin_id: str,
    db: AsyncIOMotorDatabase = Depends(get_database),
    superadmin: dict = Depends(get_current_superadmin)
):
    """Verify an admin by ID"""
    
    # Find admin using string ID
    admin = await admins_collection.find_one({"_id": admin_id})
    if not admin:
        raise HTTPException(status_code=404, detail="Admin not found")

    if admin.get("is_verified"):
        raise HTTPException(status_code=400, detail="Admin is already verified")

    # Update admin verification status
    result = await admins_collection.update_one(
        {"_id": admin_id},
        {
            "$set": {
                "is_verified": True,
                "verified_at": get_current_datetime(),
                "verified_by": superadmin["superadmin_id"]
            }
        }
    )

    if result.modified_count == 0:
        raise HTTPException(status_code=400, detail="Failed to verify admin")

    # Send approval email
    email = admin.get("email")
    name = admin.get("name", "Admin")
    if not email:
        raise HTTPException(status_code=400, detail="Admin email not found")

    try:
        await send_approval_email(email, name)
    except Exception as e:
        # Log the error but don't fail the verification
        print(f"Error sending approval email: {e}")

    return {
        "message": "Admin verified successfully",
        "admin_id": admin_id,
        "verified_at": get_current_datetime()
    }

@router.get("/admin-stats")
async def get_admin_stats(
    db: AsyncIOMotorDatabase = Depends(get_database),
    superadmin: dict = Depends(get_current_superadmin)
):
    """Get admin statistics"""
    
    total_admins = await admins_collection.count_documents({})
    verified_admins = await admins_collection.count_documents({"is_verified": True})
    pending_admins = await admins_collection.count_documents({"is_verified": False})

    # Get recent admins
    recent_admins = await admins_collection.find({})\
        .sort("created_at", -1)\
        .limit(5)\
        .to_list(length=5)

    return {
        "total_admins": total_admins,
        "verified_admins": verified_admins,
        "pending_admins": pending_admins,
        "recent_admins": recent_admins
    }

@router.delete("/admin/{admin_id}")
async def delete_admin(
    admin_id: str,
    db: AsyncIOMotorDatabase = Depends(get_database),
    superadmin: dict = Depends(get_current_superadmin)
):
    """Delete an admin"""
    
    result = await admins_collection.delete_one({"_id": admin_id})
    
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Admin not found")

    return {
        "message": "Admin deleted successfully",
        "admin_id": admin_id
    }