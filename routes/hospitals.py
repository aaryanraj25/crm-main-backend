from fastapi import APIRouter,  Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from typing import Optional
from datetime import datetime, timezone
from geopy.distance import geodesic
from bson import ObjectId

from database import get_database, clinic_collection, attendance_collection
from models.hospitals import HospitalCreate, HospitalResponse, HospitalList
from security import get_current_admin, get_current_employee

router = APIRouter()

SEARCH_RADIUS = 200  # meters
GOOGLE_API_KEY = "your_google_places_api_key"  # Configure this in your environment

def convert_objectid_to_str(document):
    if isinstance(document, dict):
        for key, value in document.items():
            if isinstance(value, ObjectId):
                document[key] = str(value)
            elif isinstance(value, list):
                document[key] = [str(v) if isinstance(v, ObjectId) else v for v in value]
    return document

@router.post("/", response_model=HospitalResponse)
async def add_hospital(
    hospital: HospitalCreate,
    current_user: dict = Depends(get_current_admin),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    hospital_data = hospital.dict()
    hospital_data.update({
        "organization_id": current_user["organization_id"],
        "added_by": current_user["user_id"],
        "added_by_role": current_user["role"],
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc)
    })

    result = await clinic_collection.insert_one(hospital_data)
    hospital_data["id"] = str(result.inserted_id)

    return HospitalResponse(**hospital_data)

@router.get("/", response_model=HospitalList)
async def get_hospitals(
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    current_user: dict = Depends(get_current_employee),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    # Check if user is WFH (implement this based on your attendance logic)
    is_wfh = await check_if_wfh(current_user["employee_id"])

    hospitals = await clinic_collection.find({
        "organization_id": current_user["organization_id"]
    }).to_list(None)

    hospitals = [convert_objectid_to_str(hospital) for hospital in hospitals]

    if not is_wfh and latitude and longitude:
        employee_location = (latitude, longitude)
        for hospital in hospitals:
            hospital_location = (hospital["latitude"], hospital["longitude"])
            distance = geodesic(employee_location, hospital_location).meters
            hospital["distance"] = round(distance, 2)
            hospital["within_range"] = distance <= SEARCH_RADIUS

    return HospitalList(
        total_hospitals=len(hospitals),
        work_mode="WFH" if is_wfh else "Office",
        coordinates_provided=latitude is not None and longitude is not None,
        hospitals=hospitals
    )

@router.get("/admin", response_model=HospitalList)
async def get_admin_hospitals(
    current_user: dict = Depends(get_current_admin),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    hospitals = await clinic_collection.find({
        "organization_id": current_user["organization_id"]
    }).to_list(None)

    hospitals = [convert_objectid_to_str(hospital) for hospital in hospitals]

    return HospitalList(
        total_hospitals=len(hospitals),
        hospitals=hospitals
    )

async def check_if_wfh(employee_id: str) -> bool:
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    attendance = await attendance_collection.find_one({
        "employee_id": ObjectId(employee_id),
        "date": today
    })
    return attendance.get("work_from_home", False) if attendance else False