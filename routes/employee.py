from fastapi import APIRouter, HTTPException, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from typing import Optional, List
from datetime import datetime, timezone, time
from geopy.distance import geodesic
from pydantic import BaseModel, Field

from database import (
    get_database, employee_collection, admins_collection,
    attendance_collection, clinic_collection, visits_collection,
    orders_collection, client_collection, sales_collection,
    wfh_request
)
from security import get_current_employee
from models.employee import (
    ClinicModel, ClientModel, WFHRequest,
    CheckInRequest, CheckOutRequest, Location
)
from models.products import OrderCreate
from utils import (
    generate_random_id, generate_visit_id, generate_order_id,
    get_current_datetime
)

router = APIRouter()

class LocationData(BaseModel):
    latitude: Optional[float] = Field(None, description="Latitude of employee")
    longitude: Optional[float] = Field(None, description="Longitude of employee")

@router.get("/profile")
async def get_employee_profile(
    employee: dict = Depends(get_current_employee),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    employee_id = employee.get("employee_id")
    
    if not employee_id:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    employee_data = await employee_collection.find_one(
        {"_id": employee_id},
        {"password": 0}
    )
    
    if not employee_data:
        raise HTTPException(status_code=404, detail="Employee not found")
    
    admin_id = employee_data.get("admin_id")
    if admin_id:
        admin_data = await admins_collection.find_one(
            {"_id": admin_id},
            {"password": 0}
        )
    else:
        admin_data = None
    
    return {
        "employee_profile": employee_data,
        "admin_profile": admin_data
    }

@router.post("/clock-in")
async def clock_in(
    location: LocationData = Depends(),
    work_from_home: bool = False,
    employee: dict = Depends(get_current_employee),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    attendance_collection = db["attendance"]
    employee_collection = db["employee"]
    employee_id = employee.get("employee_id")

    if not employee_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    existing_entry = await attendance_collection.find_one({
        "employee_id": employee_id,
        "date": today
    })

    if existing_entry:
        raise HTTPException(status_code=400, detail="Already clocked in for today")

    attendance_data = {
        "_id": generate_random_id("ATT"),
        "employee_id": employee_id,
        "clock_in_time": get_current_datetime(),
        "date": today,
        "work_from_home": work_from_home,
        "organization_id": employee.get("organization_id")
    }

    if not work_from_home and location.latitude and location.longitude:
        attendance_data["clock_in_location"] = {
            "latitude": location.latitude,
            "longitude": location.longitude
        }

    await attendance_collection.insert_one(attendance_data)
    await employee_collection.update_one(
        {"_id": employee_id},
        {"$set": {"is_active": True}}
    )

    return {
        "message": "Clock-in successful",
        "clock_in_time": attendance_data["clock_in_time"],
        "work_from_home": work_from_home
    }

@router.get("/clock-in-time")
async def get_clock_in_time(
    employee: dict = Depends(get_current_employee),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    attendance_collection = db["attendance"]
    employee_id = employee.get("employee_id")

    if not employee_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    attendance_entry = await attendance_collection.find_one({
        "employee_id": employee_id,
        "date": today
    })

    if not attendance_entry:
        raise HTTPException(status_code=404, detail="No clock-in record found for today")

    response = {
        "attendance_id": attendance_entry["_id"],
        "clock_in_time": attendance_entry["clock_in_time"],
        "work_from_home": attendance_entry.get("work_from_home", False)
    }

    # Add clock-out information if available
    if "clock_out_time" in attendance_entry:
        response["clock_out_time"] = attendance_entry["clock_out_time"]
        response["total_hours"] = attendance_entry.get("total_hours", 0)

    # Add location information if available
    if "clock_in_location" in attendance_entry:
        response["clock_in_location"] = attendance_entry["clock_in_location"]
    
    if "clock_out_location" in attendance_entry:
        response["clock_out_location"] = attendance_entry["clock_out_location"]

    return response

@router.post("/clock-out")
async def clock_out(
    location: LocationData = Depends(),
    employee: dict = Depends(get_current_employee),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    attendance_collection = db["attendance"]
    employee_collection = db["employee"]
    employee_id = employee.get("employee_id")

    if not employee_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    attendance_entry = await attendance_collection.find_one({
        "employee_id": employee_id,
        "date": today
    })

    if not attendance_entry:
        raise HTTPException(status_code=400, detail="You have not clocked in today")

    if "clock_out_time" in attendance_entry:
        raise HTTPException(status_code=400, detail="Already clocked out for today")

    clock_out_time = get_current_datetime()
    clock_in_time = attendance_entry["clock_in_time"]

    if clock_in_time.tzinfo is None:
        clock_in_time = clock_in_time.replace(tzinfo=timezone.utc)

    total_hours = (clock_out_time - clock_in_time).total_seconds() / 3600

    update_data = {
        "clock_out_time": clock_out_time,
        "total_hours": total_hours
    }

    if not attendance_entry.get("work_from_home") and location.latitude and location.longitude:
        update_data["clock_out_location"] = {
            "latitude": location.latitude,
            "longitude": location.longitude
        }

    await attendance_collection.update_one(
        {"_id": attendance_entry["_id"]},
        {"$set": update_data}
    )

    await employee_collection.update_one(
        {"_id": employee_id},
        {"$set": {"is_active": False}}
    )

    return {
        "message": "Clock-out successful",
        "clock_out_time": clock_out_time
    }


@router.post("/location")
async def post_employee_location(
    latitude: float,
    longitude: float,
    employee: dict = Depends(get_current_employee)
):
    employee_id = employee.get("employee_id")

    if not employee_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    location_data = {
        "latitude": latitude,
        "longitude": longitude,
        "updated_at": get_current_datetime()
    }

    await employee_collection.update_one(
        {"_id": employee_id},
        {"$set": {"location": location_data}}
    )

    return {
        "message": "Location updated successfully",
        "location": location_data
    }

@router.post("/clinics")
async def add_clinic(
    clinic: ClinicModel,
    employee: dict = Depends(get_current_employee)
):
    employee_id = employee.get("employee_id")
    
    if not employee_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    clinic_data = clinic.model_dump()
    clinic_data.update({
        "employee_id": employee_id,
        "organization_id": employee.get("organization_id"),
        "created_at": get_current_datetime(),
        "_id": generate_random_id("CLI")
    })

    result = await clinic_collection.insert_one(clinic_data)

    return {
        "message": "Clinic added successfully",
        "clinic_id": str(result.inserted_id)
    }

@router.post("/clients")
async def add_client(
    client: ClientModel,
    employee: dict = Depends(get_current_employee)
):
    employee_id = employee.get("employee_id")
    
    if not employee_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    clinic = await clinic_collection.find_one({"_id": client.clinic_id})
    if not clinic:
        raise HTTPException(status_code=404, detail="Clinic not found")

    client_data = client.model_dump()
    client_data.update({
        "employee_id": employee_id,
        "organization_id": employee.get("organization_id"),
        "created_at": get_current_datetime(),
        "_id": generate_random_id("CLN")
        
    })

    result = await client_collection.insert_one(client_data)

    return {
        "message": "Client added successfully",
        "client_id": str(result.inserted_id)
    }

@router.post("/wfh-request")
async def request_wfh(
    request: WFHRequest,
    employee: dict = Depends(get_current_employee)
):
    employee_id = employee.get("employee_id")

    if not employee_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    wfh_data = {
        "employee_id": employee_id,
        "organization_id": employee.get("organization_id"),
        "date": request.date,
        "reason": request.reason,
        "status": request.status,
        "created_at": get_current_datetime(),
        "_id": generate_random_id("WFH")
    }

    result = await wfh_request.insert_one(wfh_data)

    return {
        "message": "WFH request submitted successfully",
        "request_id": str(result.inserted_id)
    }

@router.post("/check-in")
async def check_in(
    request: CheckInRequest,
    employee: dict = Depends(get_current_employee)
):
    employee_id = employee.get("employee_id")

    if not employee_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    clinic = await clinic_collection.find_one({"_id": request.clinic_id})
    if not clinic:
        raise HTTPException(status_code=404, detail="Clinic not found")

    visit_id = generate_visit_id()
    visit_data = {
        "_id": visit_id,
        "employee_id": employee_id,
        "clinic_id": request.clinic_id,
        "organization_id": employee.get("organization_id"),
        "check_in_time": get_current_datetime(),
        "locations": [{
            "latitude": request.latitude,
            "longitude": request.longitude,
            "timestamp": get_current_datetime()
        }]
    }

    await visits_collection.insert_one(visit_data)

    return {
        "message": "Check-in successful",
        "visit_id": visit_id
    }

@router.post("/update-location")
async def update_location(
    location: Location,
    employee: dict = Depends(get_current_employee)
):
    employee_id = employee.get("employee_id")

    if not employee_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    active_visit = await visits_collection.find_one({
        "employee_id": employee_id,
        "check_out_time": {"$exists": False}
    })

    if not active_visit:
        raise HTTPException(status_code=400, detail="No active visit found")

    await visits_collection.update_one(
        {"_id": active_visit["_id"]},
        {
            "$push": {
                "locations": {
                    "latitude": location.latitude,
                    "longitude": location.longitude,
                    "timestamp": location.timestamp
                }
            }
        }
    )

    return {"message": "Location updated successfully"}

@router.post("/check-out/{visit_id}")
async def check_out(
    visit_id: str,
    request: CheckOutRequest,
    employee: dict = Depends(get_current_employee)
):
    employee_id = employee.get("employee_id")

    if not employee_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    visit = await visits_collection.find_one({
        "_id": visit_id,
        "employee_id": employee_id
    })

    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")

    if "check_out_time" in visit:
        raise HTTPException(status_code=400, detail="Already checked out")

    # Get current UTC time
    now_utc = datetime.now(timezone.utc)
    auto_checkout_time = time(18, 29)  # 6:29 PM UTC

    # If time is before 6:29 PM UTC and this is a manual request, allow check-out
    if now_utc.time() < auto_checkout_time and not request.notes:
        raise HTTPException(status_code=400, detail="Too early to auto check out")

    locations = visit.get("locations", [])
    total_distance = sum(
        geodesic(
            (locations[i]["latitude"], locations[i]["longitude"]),
            (locations[i + 1]["latitude"], locations[i + 1]["longitude"])
        ).kilometers
        for i in range(len(locations) - 1)
    )

    # Perform the update
    await visits_collection.update_one(
        {"_id": visit_id},
        {
            "$set": {
                "check_out_time": now_utc,
                "notes": request.notes,
                "total_distance": round(total_distance, 2)
            }
        }
    )

    return {
        "message": "Check-out successful",
        "total_distance": round(total_distance, 2)
    }


@router.post("/orders/add")
async def add_order(
    order: OrderCreate,
    employee: dict = Depends(get_current_employee)
):
    employee_id = employee.get("employee_id")
    organization_id = employee.get("organization_id")
    
    if not employee_id or not organization_id:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    order_id = generate_order_id()
    order_data = order.model_dump()
    order_data.update({
        "_id": order_id,
        "employee_id": employee_id,
        "organization_id": organization_id,
        "created_at": get_current_datetime(),
        "status": "Pending"
    })
    
    result = await orders_collection.insert_one(order_data)
    
    if not result.inserted_id:
        raise HTTPException(status_code=500, detail="Failed to place the order")
    
    return {
        "message": "Order placed successfully",
        "order_id": order_id
    }

@router.get("/stats")
async def get_employee_stats(
    employee: dict = Depends(get_current_employee)
):
    employee_id = employee.get("employee_id")
    organization_id = employee.get("organization_id")

    if not employee_id or not organization_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    # Sales statistics
    total_sales = await sales_collection.aggregate([
        {"$match": {"employee_id": employee_id}},
        {"$group": {"_id": None, "total": {"$sum": "$total_amount"}}}
    ]).to_list(length=1)

    # Visit statistics
    total_visits = await visits_collection.count_documents({
        "employee_id": employee_id
    })

    # Calculate rank
    all_employees_sales = await sales_collection.aggregate([
        {"$match": {"organization_id": organization_id}},
        {
            "$group": {
                "_id": "$employee_id",
                "total_sales": {"$sum": "$total_amount"}
            }
        },
        {"$sort": {"total_sales": -1}}
    ]).to_list(length=None)

    rank = next(
        (index + 1 for index, emp in enumerate(all_employees_sales)
         if emp["_id"] == employee_id),
        len(all_employees_sales)
    )

    # Get unique clients
    unique_clients = await client_collection.distinct(
        "client_id",
        {"employee_id": employee_id}
    )

    return {
        "total_sales": total_sales[0]["total"] if total_sales else 0,
        "total_visits": total_visits,
        "performance": {
            "rank": rank,
            "total_clients": len(unique_clients)
        }
    }