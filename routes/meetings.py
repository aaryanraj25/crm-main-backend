from fastapi import APIRouter, HTTPException, Depends, Query
from motor.motor_asyncio import AsyncIOMotorDatabase
from typing import List, Optional
from datetime import datetime, timedelta
from models.meetings import (
    MeetingCreate, MeetingCheckOut, MeetingResponse,
    MeetingSummary, MeetingType
)
from database import (
    get_database, visits_collection, client_collection,
    clinic_collection
)
from security import get_current_employee
from utils import generate_visit_id, generate_order_id

router = APIRouter()

@router.post("/check-in", response_model=MeetingResponse)
async def meeting_check_in(
    request: MeetingCreate,
    employee: dict = Depends(get_current_employee),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """Check in for a meeting"""
    employee_id = employee.get("employee_id")
    organization_id = employee.get("organization_id")

    if not organization_id:
        raise HTTPException(status_code=401, detail="Organization ID is required")

    # Verify clinic exists
    clinic = await clinic_collection.find_one({
        "_id": request.clinic_id,
        "organization_id": organization_id
    })
    if not clinic:
        raise HTTPException(status_code=404, detail="Clinic not found")

    # Verify client exists
    if not request.client_id:
        raise HTTPException(status_code=400, detail="Client ID is required")

    client = await client_collection.find_one({
        "_id": request.client_id,
        "organization_id": organization_id
    })
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    # Check for active meeting
    active_meeting = await visits_collection.find_one({
        "employee_id": employee_id,
        "organization_id": organization_id,
        "check_out_time": {"$exists": False}
    })
    if active_meeting:
        raise HTTPException(
            status_code=400,
            detail="Already have an active meeting. Please check out first."
        )

    # Create meeting
    visit_id = generate_visit_id()
    while await visits_collection.find_one({"_id": visit_id}):
        visit_id = generate_visit_id()

    meeting_data = {
        "_id": visit_id,
        "organization_id": organization_id,
        "clinic_id": request.clinic_id,
        "clinic_name": clinic["name"],
        "client_id": request.client_id,
        "check_in_time": datetime.now(),
        "latitude": request.latitude,
        "longitude": request.longitude,
        "employee_id": employee_id,
        "created_at": datetime.now()
    }

    await visits_collection.insert_one(meeting_data)

    # Get complete meeting data
    meeting = await visits_collection.find_one({"_id": visit_id})
    meeting["client"] = client

    return MeetingResponse(**meeting)

@router.post("/check-out/{meeting_id}", response_model=MeetingResponse)
async def meeting_check_out(
    meeting_id: str,
    request: MeetingCheckOut,
    employee: dict = Depends(get_current_employee),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """Check out from a meeting"""
    employee_id = employee.get("employee_id")
    organization_id = employee.get("organization_id")
    employee_name = employee.get("name")

    if not organization_id:
        raise HTTPException(status_code=401, detail="Organization ID is required")

    # Get meeting
    meeting = await visits_collection.find_one({
        "_id": meeting_id,
        "employee_id": employee_id,
        "organization_id": organization_id
    })

    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    if "check_out_time" in meeting:
        raise HTTPException(status_code=400, detail="Already checked out")
    
    # Check if 10 minutes have elapsed since check-in
    current_time = datetime.now()
    check_in_time = meeting["check_in_time"]
    min_checkout_time = check_in_time + timedelta(minutes=10)
    
    if current_time < min_checkout_time:
        # Calculate remaining time in minutes and seconds
        remaining_time = min_checkout_time - current_time
        remaining_minutes = int(remaining_time.total_seconds() // 60)
        remaining_seconds = int(remaining_time.total_seconds() % 60)
        
        raise HTTPException(
            status_code=429,  # Too Many Requests status code for rate limiting
            detail=f"Cannot check out before 10 minutes have elapsed. {remaining_minutes}m {remaining_seconds}s remaining."
        )

    # Create order if products are provided
    order_id = None
    if request.products:
        # Get clinic details
        clinic = await clinic_collection.find_one({"_id": meeting["clinic_id"]})

        # Convert products to OrderItem format
        order_items = [
            OrderItem(
                product_id=p.product_id,
                name=p.name,
                quantity=p.quantity if hasattr(p, 'quantity') else None,
                price=p.price if hasattr(p, 'price') else None,
                total=p.total
            ) for p in request.products
        ]

        total_amount = sum(item.total for item in order_items)

        # Create order data
        order_data = OrderCreate(
            clinic_id=meeting["clinic_id"],
            items=order_items,
            notes=request.notes,
            total_amount=total_amount,
            status=OrderStatus.PROSPECTIVE
        )

        order_id = generate_order_id()
        while await orders_collection.find_one({"_id": order_id}):
            order_id = generate_order_id()

        order = {
            "order_id": order_id,  # Using order_id instead of _id
            **order_data.dict(),
            "organization_id": organization_id,
            "employee_id": employee_id,
            "admin_id": None,
            "meeting_id": meeting_id,
            "created_at": datetime.now(),
            "created_by_name": employee_name,
            "clinic_name": clinic["name"]
        }

        await orders_collection.insert_one(order)

    # Update meeting
    update_data = {
        "check_out_time": datetime.now(),
        "meeting_type": request.meeting_type,
        "notes": request.notes,
        "updated_at": datetime.now()
    }

    if order_id:
        update_data["order_id"] = order_id

    await visits_collection.update_one(
        {"_id": meeting_id},
        {"$set": update_data}
    )

    # Get updated meeting with client info
    updated_meeting = await visits_collection.find_one({"_id": meeting_id})
    client = await client_collection.find_one({"_id": updated_meeting["client_id"]})
    updated_meeting["client"] = client

    return MeetingResponse(**updated_meeting)

@router.get("/first-meetings", response_model=List[MeetingResponse])
async def get_first_meetings(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    clinic_id: Optional[str] = None,
    employee: dict = Depends(get_current_employee),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """Get all first meetings"""
    organization_id = employee.get("organization_id")

    if not organization_id:
        raise HTTPException(status_code=401, detail="Organization ID is required")

    # Build query
    query = {
        "organization_id": organization_id,
        "meeting_type": MeetingType.FIRST_MEETING,
        "check_out_time": {"$exists": True}
    }

    if start_date:
        query["check_in_time"] = {"$gte": start_date}
    if end_date:
        query["check_out_time"] = {"$lte": end_date}
    if clinic_id:
        query["clinic_id"] = clinic_id

    meetings = await visits_collection.find(query) \
        .sort("check_in_time", -1) \
        .skip(skip) \
        .limit(limit) \
        .to_list(length=None)

    # Add client info
    for meeting in meetings:
        client = await client_collection.find_one({"_id": meeting["client_id"]})
        meeting["client"] = client

    return [MeetingResponse(**meeting) for meeting in meetings]

@router.get("/completed", response_model=List[MeetingResponse])
async def get_completed_meetings(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    meeting_type: Optional[MeetingType] = None,
    clinic_id: Optional[str] = None,
    client_id: Optional[str] = None,
    search: Optional[str] = None,
    employee: dict = Depends(get_current_employee),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """Get completed meetings with filters, ensuring employee-specific client meetings"""
    employee_id = employee.get("employee_id")
    organization_id = employee.get("organization_id")

    if not organization_id:
        raise HTTPException(status_code=401, detail="Organization ID is required")

    # Build query
    query = {
        "organization_id": organization_id,
        "employee_id": employee_id,
        "check_out_time": {"$exists": True}
    }

    if start_date:
        query["check_in_time"] = {"$gte": start_date}
    if end_date:
        query["check_out_time"] = {"$lte": end_date}
    if meeting_type:
        query["meeting_type"] = meeting_type
    if clinic_id:
        query["clinic_id"] = clinic_id
    if client_id:
        query["client_id"] = client_id
    if search:
        query["$or"] = [
            {"clinic_name": {"$regex": search, "$options": "i"}},
            {"client.name": {"$regex": search, "$options": "i"}}
        ]

    meetings = await visits_collection.find(query) \
        .sort("check_out_time", -1) \
        .skip(skip) \
        .limit(limit) \
        .to_list(length=None)

    # Add client info
    for meeting in meetings:
        client = await client_collection.find_one({"_id": meeting["client_id"]})
        meeting["client"] = client

    return [MeetingResponse(**meeting) for meeting in meetings]

@router.get("/active", response_model=Optional[MeetingResponse])
async def get_active_meeting(
    client_id: Optional[str] = None,
    employee: dict = Depends(get_current_employee),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """Get employee's active meeting, optionally filtered by client"""
    employee_id = employee.get("employee_id")
    organization_id = employee.get("organization_id")

    if not organization_id:
        raise HTTPException(status_code=401, detail="Organization ID is required")

    # Build query
    query = {
        "employee_id": employee_id,
        "organization_id": organization_id,
        "check_out_time": {"$exists": False}
    }

    # Add client_id filter if provided
    if client_id:
        query["client_id"] = client_id

    meeting = await visits_collection.find_one(query)

    if meeting:
        client = await client_collection.find_one({"_id": meeting["client_id"]})
        meeting["client"] = client
        return MeetingResponse(**meeting)

    return None

@router.get("/summary", response_model=MeetingSummary)
async def get_meetings_summary(
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    employee: dict = Depends(get_current_employee),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """Get meetings summary"""
    organization_id = employee.get("organization_id")

    if not organization_id:
        raise HTTPException(status_code=401, detail="Organization ID is required")

    # Build query
    query = {
        "organization_id": organization_id,
        "check_out_time": {"$exists": True}
    }

    if start_date or end_date:
        date_query = {}
        if start_date:
            date_query["$gte"] = start_date
        if end_date:
            date_query["$lte"] = end_date
        query["check_in_time"] = date_query

    meetings = await visits_collection.find(query).to_list(length=None)

    # Calculate summary
    meeting_types_count = {}
    unique_clients = set()
    unique_clinics = set()
    total_products = 0

    for meeting in meetings:
        meeting_type = meeting.get("meeting_type")
        if meeting_type:
            meeting_types_count[meeting_type] = meeting_types_count.get(meeting_type, 0) + 1

        unique_clients.add(meeting["client_id"])
        unique_clinics.add(meeting["clinic_id"])

        products = meeting.get("products", [])
        total_products += sum(product["quantity"] for product in products)

    return {
        "total_meetings": len(meetings),
        "meetings_by_type": meeting_types_count,
        "total_products_disbursed": total_products,
        "unique_clients_visited": len(unique_clients),
        "unique_clinics_visited": len(unique_clinics),
        "date_range": {
            "start": start_date,
            "end": end_date
        }
    }