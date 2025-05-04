from fastapi import APIRouter, HTTPException, Depends, Query
from motor.motor_asyncio import AsyncIOMotorDatabase
from typing import List, Optional
from datetime import datetime
from models.clients import (
    ClientCreate, ClientUpdate, ClientResponse, ClientCapacity
)
from database import get_database, client_collection, clinic_collection
from security import get_current_employee, get_current_admin
from utils import generate_random_id

router = APIRouter()

# Admin Routes
@router.post("/admin", response_model=ClientResponse)
async def admin_create_client(
    client: ClientCreate,
    admin: dict = Depends(get_current_admin),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """Admin: Create a new client"""
    admin_id = admin.get("admin_id")
    organization_id = admin.get("organization_id")

    if not organization_id:
        raise HTTPException(status_code=401, detail="Organization ID is required")

    # Verify clinic exists
    clinic = await clinic_collection.find_one({
        "_id": client.clinic_id,
        "organization_id": organization_id
    })
    if not clinic:
        raise HTTPException(status_code=404, detail="Clinic not found")

    # Check if client with same mobile exists
    existing_client = await client_collection.find_one({
        "mobile": client.mobile,
        "organization_id": organization_id
    })
    if existing_client:
        raise HTTPException(status_code=400, detail="Client with this mobile already exists")

    # Create client
    client_data = client.dict()
    client_data.update({
        "_id": generate_random_id("CLT"),
        "organization_id": organization_id,
        "clinic_name": clinic["name"],
        "created_at": datetime.now(),
        "created_by": admin_id,
        "created_by_type": "admin"  # To distinguish between admin and employee creation
    })

    await client_collection.insert_one(client_data)
    return ClientResponse(**client_data)

@router.get("/admin", response_model=List[ClientResponse])
async def admin_get_clients(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),  # Admin can fetch more records
    clinic_id: Optional[str] = None,
    capacity: Optional[ClientCapacity] = None,
    search: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    sort_by: str = Query("created_at", description="Sort field: created_at, name, clinic_name"),
    sort_order: int = Query(-1, description="Sort order: -1 for descending, 1 for ascending"),
    admin: dict = Depends(get_current_admin),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """Admin: Get all clients with advanced filters"""
    organization_id = admin.get("organization_id")

    if not organization_id:
        raise HTTPException(status_code=401, detail="Organization ID is required")

    # Build query
    query = {"organization_id": organization_id}

    if clinic_id:
        query["clinic_id"] = clinic_id
    if capacity:
        query["capacity"] = capacity
    if start_date:
        query["created_at"] = {"$gte": start_date}
    if end_date:
        if "created_at" in query:
            query["created_at"]["$lte"] = end_date
        else:
            query["created_at"] = {"$lte": end_date}
    if search:
        query["$or"] = [
            {"name": {"$regex": search, "$options": "i"}},
            {"mobile": {"$regex": search, "$options": "i"}},
            {"email": {"$regex": search, "$options": "i"}},
            {"clinic_name": {"$regex": search, "$options": "i"}}
        ]

    # Get total count for pagination
    total_count = await client_collection.count_documents(query)

    # Get clients with sorting
    clients = await client_collection.find(query) \
        .sort(sort_by, sort_order) \
        .skip(skip) \
        .limit(limit) \
        .to_list(length=None)

    return [ClientResponse(**client) for client in clients]

@router.get("/admin/{client_id}", response_model=ClientResponse)
async def admin_get_client(
    client_id: str,
    admin: dict = Depends(get_current_admin),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """Admin: Get a specific client"""
    organization_id = admin.get("organization_id")

    if not organization_id:
        raise HTTPException(status_code=401, detail="Organization ID is required")

    client = await client_collection.find_one({
        "_id": client_id,
        "organization_id": organization_id
    })

    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    return ClientResponse(**client)

@router.put("/admin/{client_id}", response_model=ClientResponse)
async def admin_update_client(
    client_id: str,
    client_update: ClientUpdate,
    admin: dict = Depends(get_current_admin),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """Admin: Update a client"""
    organization_id = admin.get("organization_id")

    if not organization_id:
        raise HTTPException(status_code=401, detail="Organization ID is required")

    # Check if client exists
    client = await client_collection.find_one({
        "_id": client_id,
        "organization_id": organization_id
    })

    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    # Update client
    update_data = client_update.dict(exclude_unset=True)
    if update_data:
        update_data.update({
            "updated_at": datetime.now(),
            "updated_by": admin.get("admin_id"),
            "updated_by_type": "admin"
        })

        await client_collection.update_one(
            {"_id": client_id},
            {"$set": update_data}
        )

    updated_client = await client_collection.find_one({"_id": client_id})
    return ClientResponse(**updated_client)

# Employee Routes
@router.post("", response_model=ClientResponse)
async def create_client(
    client: ClientCreate,
    employee: dict = Depends(get_current_employee),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """Employee: Create a new client"""
    employee_id = employee.get("employee_id")
    organization_id = employee.get("organization_id")

    if not organization_id:
        raise HTTPException(status_code=401, detail="Organization ID is required")

    # Verify clinic exists
    clinic = await clinic_collection.find_one({
        "_id": client.clinic_id,
        "organization_id": organization_id
    })
    if not clinic:
        raise HTTPException(status_code=404, detail="Clinic not found")

    # Check if client with same mobile exists
    existing_client = await client_collection.find_one({
        "mobile": client.mobile,
        "organization_id": organization_id
    })
    if existing_client:
        raise HTTPException(status_code=400, detail="Client with this mobile already exists")

    # Create client
    client_data = client.dict()
    client_data.update({
        "_id": generate_random_id("CLT"),
        "organization_id": organization_id,
        "clinic_name": clinic["name"],
        "created_at": datetime.now(),
        "created_by": employee_id,
        "created_by_type": "employee"
    })

    await client_collection.insert_one(client_data)
    return ClientResponse(**client_data)

@router.get("", response_model=List[ClientResponse])
async def get_clients(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    clinic_id: Optional[str] = None,
    capacity: Optional[ClientCapacity] = None,
    search: Optional[str] = None,
    employee: dict = Depends(get_current_employee),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """Employee: Get all clients with filters"""
    organization_id = employee.get("organization_id")

    if not organization_id:
        raise HTTPException(status_code=401, detail="Organization ID is required")

    # Build query
    query = {"organization_id": organization_id}

    if clinic_id:
        query["clinic_id"] = clinic_id
    if capacity:
        query["capacity"] = capacity
    if search:
        query["$or"] = [
            {"name": {"$regex": search, "$options": "i"}},
            {"mobile": {"$regex": search, "$options": "i"}},
            {"email": {"$regex": search, "$options": "i"}}
        ]

    clients = await client_collection.find(query) \
        .sort("created_at", -1) \
        .skip(skip) \
        .limit(limit) \
        .to_list(length=None)

    return [ClientResponse(**client) for client in clients]

@router.get("/{client_id}", response_model=ClientResponse)
async def get_client(
    client_id: str,
    employee: dict = Depends(get_current_employee),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """Employee: Get a specific client"""
    organization_id = employee.get("organization_id")

    if not organization_id:
        raise HTTPException(status_code=401, detail="Organization ID is required")

    client = await client_collection.find_one({
        "_id": client_id,
        "organization_id": organization_id
    })

    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    return ClientResponse(**client)

@router.put("/{client_id}", response_model=ClientResponse)
async def update_client(
    client_id: str,
    client_update: ClientUpdate,
    employee: dict = Depends(get_current_employee),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """Employee: Update a client"""
    organization_id = employee.get("organization_id")

    if not organization_id:
        raise HTTPException(status_code=401, detail="Organization ID is required")

    # Check if client exists
    client = await client_collection.find_one({
        "_id": client_id,
        "organization_id": organization_id
    })

    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    # Update client
    update_data = client_update.dict(exclude_unset=True)
    if update_data:
        update_data.update({
            "updated_at": datetime.now(),
            "updated_by": employee.get("employee_id"),
            "updated_by_type": "employee"
        })

        await client_collection.update_one(
            {"_id": client_id},
            {"$set": update_data}
        )

    updated_client = await client_collection.find_one({"_id": client_id})
    return ClientResponse(**updated_client)