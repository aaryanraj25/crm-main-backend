from fastapi import APIRouter, HTTPException, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from database import get_database, admins_collection
from bson import ObjectId
from security import get_current_superadmin

router = APIRouter()

@router.get("/pending_admins")
async def get_pending_admins(
    page: int = 1,  # Default page number
    page_size: int = 10,  # Default items per page
    db: AsyncIOMotorDatabase = Depends(get_database),
    superadmin: dict = Depends(get_current_superadmin)
):
    """Fetch pending admins with pagination"""

    if page < 1 or page_size < 1:
        raise HTTPException(status_code=400, detail="Page and page_size must be greater than 0")

    skip = (page - 1) * page_size  # Calculate skip value

    total_pending_admins = await admins_collection.count_documents({"is_verified": False})  # Total count

    pending_admins = await admins_collection.find({"is_verified": False})\
        .skip(skip).limit(page_size).to_list(length=page_size)

    for admin in pending_admins:
        admin["_id"] = str(admin["_id"])  # Convert ObjectId to string

    return {
        "pending_admins": pending_admins,
        "total": total_pending_admins,
        "page": page,
        "page_size": page_size,
        "total_pages": (total_pending_admins + page_size - 1) // page_size  # Calculate total pages
    }


@router.put("/verify-admin/{admin_id}")
async def verify_admin(
    admin_id: str,
    db: AsyncIOMotorDatabase = Depends(get_database),
    superadmin: dict = Depends(get_current_superadmin)
):
    admin = await admins_collection.find_one({"_id": admin_id})
    try:
        object_id = ObjectId(admin_id)  # ✅ Convert string ID to ObjectId
    except:  # noqa: E722
        raise HTTPException(status_code=400, detail="Invalid Admin ID format")

    admin = await admins_collection.find_one({"_id": object_id})
    if not admin:
        raise HTTPException(status_code=404, detail="Admin not found")

    if admin.get("is_verified"):
        raise HTTPException(status_code=400, detail="Admin is already verified")

    await admins_collection.update_one({"_id": object_id}, {"$set": {"is_verified": True}})

    return {"message": "Admin verified successfully"}