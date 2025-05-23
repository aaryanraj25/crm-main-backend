# routes/superadmin.py
from fastapi import APIRouter, HTTPException, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from database import get_database, admins_collection
from security import get_current_superadmin
from services.email_service import send_approval_email
from utils import get_current_datetime

router = APIRouter()

@router.get("/pending_admins")  # Changed from pending-admins to pending_admins
async def get_pending_admins(
    page: int = 1,
    page_size: int = 10,
    db: AsyncIOMotorDatabase = Depends(get_database),
    superadmin: dict = Depends(get_current_superadmin)
):
    try:
        if page < 1 or page_size < 1:
            raise HTTPException(
                status_code=400,
                detail="Page and page_size must be greater than 0"
            )

        # Query for pending admins
        query = {"is_verified": False}

        # Get total count
        total_pending_admins = await admins_collection.count_documents(query)

        # Calculate skip
        skip = (page - 1) * page_size

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
    except Exception as e:
        print(f"Error in get_pending_admins: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

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

@router.put("/verify-admin/{admin_id}")  # Notice the hyphen here to match the URL
async def verify_admin(
    admin_id: str,
    db: AsyncIOMotorDatabase = Depends(get_database),
    superadmin: dict = Depends(get_current_superadmin)
):
    try:
        # Print debug info
        print(f"Verifying admin with ID: {admin_id}")

        # Find the admin
        admin = await admins_collection.find_one({"_id": admin_id})
        if not admin:
            raise HTTPException(status_code=404, detail=f"Admin not found with ID: {admin_id}")

        if admin.get("is_verified"):
            raise HTTPException(status_code=400, detail="Admin is already verified")

        # Update admin
        result = await admins_collection.update_one(
            {"_id": admin_id},
            {
                "$set": {
                    "is_verified": True,
                    "verified_at": get_current_datetime(),
                    "verified_by": superadmin.get("superadmin_id", "SUPER-ADMIN")
                }
            }
        )

        if result.modified_count == 0:
            raise HTTPException(status_code=400, detail="Failed to verify admin")

        # Send approval email
        try:
            email = admin.get("email")
            name = admin.get("name", "Admin")
            await send_approval_email(email, name)
        except Exception as e:
            print(f"Warning: Failed to send approval email: {e}")
            # Don't fail the verification if email fails

        return {
            "message": "Admin verified successfully",
            "admin_id": admin_id,
            "verified_at": get_current_datetime()
        }

    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error in verify_admin: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

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