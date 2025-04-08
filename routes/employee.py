
from database import get_database, employee_collection, admins_collection, attendance_collection, clinic_collection, visits_collection, orders_collection, client_collection,sales_collection
from security import get_current_employee
from bson import ObjectId
from fastapi import Depends, HTTPException, APIRouter
from motor.motor_asyncio import AsyncIOMotorDatabase
from datetime import datetime, timezone
from models.employee import ClinicModel,  CheckInRequest, ClientModel
from geopy.distance import geodesic  # Correct import
from typing import Optional
from models.products import  OrderCreate


router = APIRouter()

def convert_objectid_to_str(document):
    """Recursively converts ObjectId fields in a document to strings."""
    if isinstance(document, dict):
        for key, value in document.items():
            if isinstance(value, ObjectId):
                document[key] = str(value)
            elif isinstance(value, list):  # Handle lists containing ObjectId
                document[key] = [str(v) if isinstance(v, ObjectId) else v for v in value]
    return document

@router.get("/profile")
async def get_employee_profile(
    employee: dict = Depends(get_current_employee),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    employee_id = employee.get("employee_id")
    
    if not employee_id:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    employee_data = await employee_collection.find_one({"_id": ObjectId(employee_id)}, {"password": 0})
    
    if not employee_data:
        raise HTTPException(status_code=404, detail="Employee not found")
    
    admin_id = employee_data.get("admin_id")
    if admin_id:
        admin_data = await admins_collection.find_one({"_id": ObjectId(admin_id)}, {"password": 0})
        if not admin_data:
            raise HTTPException(status_code=404, detail="Admin not found")
        admin_data = convert_objectid_to_str(admin_data)  # Convert all ObjectId fields
    else:
        admin_data = None
    
    employee_data = convert_objectid_to_str(employee_data)  # Convert all ObjectId fields
    
    return {
        "employee_profile": employee_data,
        "admin_profile": admin_data
    }

@router.post("/clock-in")
async def clock_in(
    work_from_home: bool = False,  # Default to False if not provided
    employee: dict = Depends(get_current_employee)
):
    employee_id = employee.get("employee_id")
    
    if not employee_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    existing_entry = await attendance_collection.find_one({
        "employee_id": ObjectId(employee_id),
        "date": today
    })

    if existing_entry:
        raise HTTPException(status_code=400, detail="Already clocked in for today")

    # Insert attendance record
    attendance_data = {
        "employee_id": ObjectId(employee_id),
        "clock_in_time": datetime.now(timezone.utc),
        "date": today,
        "work_from_home": work_from_home  # Either True or False
    }
    await attendance_collection.insert_one(attendance_data)

    # Mark employee as active
    await employee_collection.update_one(
        {"_id": ObjectId(employee_id)},
        {"$set": {"is_active": True}}
    )

    return {
        "message": "Clock-in successful",
        "clock_in_time": attendance_data["clock_in_time"],
        "work_from_home": work_from_home  # Return the chosen work mode
    }    
    
    
@router.post("/clock-out")
async def clock_out(
    employee: dict = Depends(get_current_employee)
):
    employee_id = employee.get("employee_id")
    
    if not employee_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    # Find today's attendance record
    attendance_entry = await attendance_collection.find_one({
        "employee_id": ObjectId(employee_id),
        "date": today
    })

    if not attendance_entry:
        raise HTTPException(status_code=400, detail="You have not clocked in today")

    if "clock_out_time" in attendance_entry:
        raise HTTPException(status_code=400, detail="Already clocked out for today")

    # Update attendance with clock-out time and mark inactive
    clock_out_time = datetime.now(timezone.utc)
    await attendance_collection.update_one(
        {"_id": attendance_entry["_id"]},
        {"$set": {"clock_out_time": clock_out_time}}
    )

    await employee_collection.update_one(
        {"_id": ObjectId(employee_id)},
        {"$set": {"is_active": False}}  # Employee is inactive after clock-out
    )

    return {
        "message": "Clock-out successful",
        "clock_out_time": clock_out_time
    }

@router.post("/location")
async def post_employee_location(
    latitude: float,
    longitude: float,
    employee: dict = Depends(get_current_employee),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """
    Allows an employee to post their current location (latitude and longitude).
    """
    employee_id = employee.get("employee_id")

    if not employee_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    # Update the employee's location in the database
    await employee_collection.update_one(
        {"_id": ObjectId(employee_id)},
        {"$set": {"location": {"latitude": latitude, "longitude": longitude, "updated_at": datetime.now(timezone.utc)}}}
    )

    return {
        "message": "Location updated successfully",
        "location": {"latitude": latitude, "longitude": longitude}
    }
    
    
@router.post("/clinics")
async def add_clinic(
    clinic: ClinicModel,
    employee: dict = Depends(get_current_employee),
    db=Depends(get_database)
):
    """Add a new clinic and associate it with an employee."""
    employee_id = employee.get("employee_id")
    
    if not employee_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    clinic_data = clinic.model_dump()
    clinic_data["employee_id"] = ObjectId(employee_id)

    # Insert into clinics collection
    inserted_clinic = await clinic_collection.insert_one(clinic_data)

    return {
        "message": "Clinic added successfully",
        "clinic_id": str(inserted_clinic.inserted_id)
    }
@router.post("/employee/clients")
async def add_client(
    client: ClientModel,
    employee: dict = Depends(get_current_employee),
    db=Depends(get_database)
):
    """Add a new client and associate it with a clinic."""
    employee_id = employee.get("employee_id")
    
    if not employee_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    # Check if the clinic exists
    clinic = await db.clinics_collection.find_one({"_id": ObjectId(client.clinic_id)})
    if not clinic:
        raise HTTPException(status_code=404, detail="Clinic not found")

    client_data = client.model_dump()
    client_data["employee_id"] = ObjectId(employee_id)
    client_data["clinic_id"] = ObjectId(client.clinic_id)

    # Insert into clients collection
    inserted_client = await client_collection.insert_one(client_data)

    return {
        "message": "Client added successfully",
        "client_id": str(inserted_client.inserted_id),
        "clinic_id": client.clinic_id
    }
 
    
@router.post("/check-in")
async def check_in(data: CheckInRequest, employee: dict = Depends(get_current_employee)):
    
    employee_id = employee.get("employee_id")
    
    if not employee_id:
        raise HTTPException(status_code=401, detail="Invalid token")
    """Allows an employee to check in only if within 100 meters of the clinic."""

    # Fetch clinic details
    clinic = await clinic_collection.find_one({"_id": ObjectId(data.clinic_id)})
    
    if not clinic:
        raise HTTPException(status_code=404, detail="Clinic not found")

    # Extract coordinates
    clinic_coords = (clinic["latitude"], clinic["longitude"])
    employee_coords = (data.latitude, data.longitude)

    # Calculate distance in meters
    distance = geodesic(clinic_coords, employee_coords).meters

    if distance > 100:
        raise HTTPException(status_code=403, detail=f"You must be within 100m to check in. Current distance: {distance:.2f}m")

    visit = {
        "employee_id": ObjectId(data.employee_id),
        "clinic_id": ObjectId(data.clinic_id),
        "check_in_time": datetime.now(timezone.utc),
        "check_out_time": None,
        "time_spent_minutes": None,
        "meeting_outcome": None,
        "notes": None,
        "follow_up_date": None
    }

    result = await visits_collection.insert_one(visit)
    return {"message": "Check-in successful", "visit_id": str(result.inserted_id)}

@router.post("/check-out")
async def check_out(visit_id: str, employee: dict = Depends(get_current_employee)):
    employee_id = employee.get("employee_id")
    
    if not employee_id:
        raise HTTPException(status_code=401, detail="Invalid token")
    """Marks check-out and calculates time spent at the clinic."""
    visit = await visits_collection.find_one({"_id": ObjectId(visit_id)})

    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")

    if visit.get("check_out_time"):
        raise HTTPException(status_code=400, detail="Already checked out")

    check_out_time = datetime.now(timezone.utc)
    visit["check_in_time"] = visit["check_in_time"].replace(tzinfo=timezone.utc)

    time_spent = (check_out_time - visit["check_in_time"]).total_seconds() // 60  # Minutes

    await visits_collection.update_one(
        {"_id": ObjectId(visit_id)},
        {"$set": {"check_out_time": check_out_time, "time_spent_minutes": time_spent}}
    )

    return {"message": "Check-out successful", "time_spent": time_spent}

@router.post("/update-meeting")
async def update_meeting(visit_id: str, outcome: str, notes: Optional[str] = None, follow_up_date: Optional[datetime] = None,employee: dict = Depends(get_current_employee)):
    employee_id = employee.get("employee_id")
    
    if not employee_id:
        raise HTTPException(status_code=401, detail="Invalid token")
    """Updates meeting outcome, notes, and follow-up date."""
    valid_outcomes = ["Interested", "Not Interested", "Follow-up Required"]
    
    if outcome not in valid_outcomes:
        raise HTTPException(status_code=400, detail="Invalid meeting outcome")

    update_data = {"meeting_outcome": outcome}
    if notes:
        update_data["notes"] = notes
    if follow_up_date:
        update_data["follow_up_date"] = follow_up_date

    result = await visits_collection.update_one({"_id": ObjectId(visit_id)}, {"$set": update_data})

    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Visit not found or no updates made")

    return {"message": "Meeting details updated successfully"}

@router.get("/stats")
async def get_employee_stats(
    db: AsyncIOMotorDatabase = Depends(get_database),
    employee: dict = Depends(get_current_employee)
):
    """
    Fetch total sales, total visits, and performance metrics for the logged-in employee.
    """
    employee_id = employee.get("employee_id")
    organization_id = employee.get("organization_id")

    if not employee_id or not organization_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    # Fetch total sales for the employee
    total_sales = await sales_collection.aggregate([
        {"$match": {"employee.id": employee_id}},
        {"$group": {"_id": None, "totalSales": {"$sum": "$total_amount"}}}
    ]).to_list(length=1)

    # Fetch total visits for the employee
    total_visits = await visits_collection.count_documents({"employee_id": ObjectId(employee_id)})

    # Fetch all employees' sales in the organization to calculate rank
    all_employees_sales = await sales_collection.aggregate([
        {"$match": {"organization_id": organization_id}},
        {
            "$group": {
                "_id": "$employee.id",
                "salesAchieved": {"$sum": "$total_amount"}
            }
        },
        {"$sort": {"salesAchieved": -1}}
    ]).to_list(length=None)

    # Calculate rank for the employee
    rank = next(
        (index + 1 for index, emp in enumerate(all_employees_sales) if emp["_id"] == employee_id),
        None
    )

    # Fetch the number of unique clients handled by the employee
    clients_count = await sales_collection.distinct("client_id", {"employee.id": employee_id})

    return {
        "totalSales": total_sales[0]["totalSales"] if total_sales else 0,
        "totalVisits": total_visits,
        "performance": {
            "salesAchieved": total_sales[0]["totalSales"] if total_sales else 0,
            "rank": rank,
            "clientsCount": len(clients_count)
        }
    }

@router.post("/orders/add", status_code=201)
async def add_order(order: OrderCreate, employee: dict = Depends(get_current_employee)):
    employee_id = employee.get("employee_id")
    organization_id = employee.get("organization_id")  # Extract organization_id
    
    if not employee_id or not organization_id:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    order_dict = order.model_dump()
    
    # ✅ Store employee_id & organization_id in the order
    order_dict["employee_id"] = employee_id
    order_dict["organization_id"] = organization_id  # Add organization_id to order
    
    # ✅ Ensure order_date is properly formatted
    
    order_dict["order_date"] = datetime.combine(order_dict["order_date"], datetime.min.time())
    
    # ✅ Insert order into MongoDB
    result = await orders_collection.insert_one(order_dict)
    
    if not result.inserted_id:
        raise HTTPException(status_code=500, detail="Failed to place the order")
    
    return {"message": "Order placed successfully", "order_id": str(result.inserted_id)}



@router.get("/employee/profile_sales")
async def get_one_employee_profile(
    current_employee: dict = Depends(get_current_employee),
    db=Depends(get_database)
):
    """Fetch Employee Profile with Sales, Attendance, Orders, Meetings, Clients & Clinics"""
    if current_employee["role"] != "employee":
        raise HTTPException(status_code=403, detail="Only employees can access this profile")

    employee_id = ObjectId(current_employee["user_id"])

    # Fetch Employee Details
    employee = await employee_collection.find_one({"_id": employee_id}, {"password": 0})
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    # Fetch Sales Made
    sales = await sales_collection.find({"employee.id": str(employee_id)}).to_list(None)

    # Fetch Attendance Records
    attendance = await attendance_collection.find({"employee_id": employee_id}).to_list(None)

    # Fetch Orders Placed
    orders = await orders_collection.find({"employee_id": str(employee_id)}).to_list(None)

    # Fetch Meetings Attended
    meetings = await visits_collection.find({"employee_id": str(employee_id)}).to_list(None)

    # Fetch Clients & Clinics Added
    clients = await client_collection.find({"added_by": str(employee_id)}).to_list(None)

    # Format Response
    return {
        "employee": {
            "id": str(employee["_id"]),
            "name": employee["name"],
            "email": employee["email"],
            "phone": employee["phone"],
            "organization": employee.get("organization", ""),
            "admin_id": str(employee.get("admin_id", "")),
            "is_active": employee.get("is_active", False)
        },
        "sales": sales,
        "attendance": attendance,
        "orders": orders,
        "meetings": meetings,
        "clients": clients
    }


