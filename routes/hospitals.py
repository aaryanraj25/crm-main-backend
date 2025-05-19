from fastapi import APIRouter, HTTPException, Depends, Query
from motor.motor_asyncio import AsyncIOMotorDatabase
from typing import List, Optional, Dict
from datetime import datetime
from geopy.distance import geodesic
import requests
from database import (
    get_database, clinic_collection, employee_collection
)
from models.hospitals import (
    HospitalCreate, HospitalResponse, HospitalType,
    HospitalList, HospitalManualCreate
)
from security import get_current_admin, get_current_employee
from utils import get_current_datetime, generate_random_id

router = APIRouter()

GOOGLE_MAPS_API_KEY = "AIzaSyAO89GizFNQftsciix7q7yL6JZHoOYSdhg"

class GooglePlacesService:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.text_search_url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
        self.details_url = "https://maps.googleapis.com/maps/api/place/details/json"

    def search_by_name(
        self,
        name: str,
        city: Optional[str] = None,
        type_: str = "hospital"
    ) -> List[Dict]:
        query = name
        if city:
            query += f", {city}"
        params = {
            "query": query,
            "type": type_,
            "key": self.api_key
        }
        response = requests.get(self.text_search_url, params=params)
        data = response.json()
        if data.get("status") != "OK":
            return []
        return data["results"]

    def get_place_details(self, place_id: str) -> Optional[Dict]:
        params = {
            "place_id": place_id,
            "fields": "name,formatted_address,geometry,formatted_phone_number,website,rating,place_id",
            "key": self.api_key
        }
        response = requests.get(self.details_url, params=params)
        data = response.json()
        if data.get("status") != "OK":
            return None
        return data["result"]

google_places = GooglePlacesService(GOOGLE_MAPS_API_KEY)

# Common search endpoint
@router.get("/search", response_model=List[dict])
async def search_hospital_by_name(
    name: str = Query(..., description="Hospital/Clinic name"),
    city: Optional[str] = Query(None, description="City name"),
    type_: str = Query("all", description="Type: hospital or clinic")
):
    """
    Search hospitals/clinics by name using Google Places API.
    This endpoint is used before adding a new hospital/clinic.
    """
    results = google_places.search_by_name(name, city, type_)
    return [
        {
            "place_id": r["place_id"],
            "name": r["name"],
            "address": r.get("formatted_address"),
            "latitude": r.get("geometry", {}).get("location", {}).get("lat"),
            "longitude": r.get("geometry", {}).get("location", {}).get("lng"),
            "rating": r.get("rating")
        }
        for r in results
    ]

# Admin Routes
@router.get("/admin/clinics", response_model=HospitalList)
async def get_admin_clinics(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    search: Optional[str] = None,
    type: Optional[HospitalType] = None,
    city: Optional[str] = None,
    state: Optional[str] = None,
    admin: dict = Depends(get_current_admin),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """Get all clinics for admin with filtering options"""
    organization_id = admin.get("organization_id")
    if not organization_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    # Build query
    query = {"organization_id": organization_id}

    if search:
        query["$or"] = [
            {"name": {"$regex": search, "$options": "i"}},
            {"address": {"$regex": search, "$options": "i"}},
            {"city": {"$regex": search, "$options": "i"}},
            {"specialties": {"$regex": search, "$options": "i"}}
        ]

    if type:
        query["type"] = type
    if city:
        query["city"] = city
    if state:
        query["state"] = state

    # Get total count
    total_count = await clinic_collection.count_documents(query)

    # Get clinics
    clinics = await clinic_collection.find(query) \
        .sort("created_at", -1) \
        .skip(skip) \
        .limit(limit) \
        .to_list(length=None)

    # Process clinics to handle _id
    processed_clinics = []
    for clinic in clinics:
        clinic['id'] = clinic.pop('_id')  # Replace _id with id
        processed_clinics.append(clinic)

    return HospitalList(
        total_hospitals=total_count,
        work_mode=None,
        coordinates_provided=False,
        hospitals=[HospitalResponse(**clinic) for clinic in processed_clinics]
    )

@router.post("/admin/clinics/google-place", response_model=HospitalResponse)
async def add_clinic_from_google_admin(
    place_id: str,
    admin: dict = Depends(get_current_admin),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """Add a clinic using Google Places API by admin"""
    organization_id = admin.get("organization_id")
    if not organization_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    # Check for duplicates
    existing = await clinic_collection.find_one({
        "google_place_id": place_id,
        "organization_id": organization_id
    })
    if existing:
        raise HTTPException(status_code=400, detail="Clinic already exists")

    # Fetch details from Google
    details = google_places.get_place_details(place_id)
    if not details:
        raise HTTPException(status_code=404, detail="Place not found")

    # Extract address components
    address_parts = details.get("formatted_address", "").split(",")

    # Generate CLN ID
    clinic_id = generate_random_id("CLN")

    clinic_data = {
        "_id": clinic_id,  # Use the CLN ID as MongoDB _id
        "id": clinic_id,   # Keep this for consistency
        "name": details["name"],
        "address": address_parts[0].strip() if address_parts else details.get("formatted_address", ""),
        "city": address_parts[-3].strip() if len(address_parts) > 3 else "",
        "state": address_parts[-2].strip() if len(address_parts) > 2 else "",
        "country": address_parts[-1].strip() if len(address_parts) > 1 else "India",
        "pincode": "",  # Extract from address if possible
        "latitude": details["geometry"]["location"]["lat"],
        "longitude": details["geometry"]["location"]["lng"],
        "phone": details.get("formatted_phone_number"),
        "website": details.get("website"),
        "google_place_id": place_id,
        "rating": details.get("rating"),
        "organization_id": organization_id,
        "added_by": admin["admin_id"],
        "added_by_role": "admin",
        "created_at": get_current_datetime(),
        "source": "google_places",
        "status": "active",
        "type": HospitalType.HOSPITAL
    }

    try:
        await clinic_collection.insert_one(clinic_data)
        # Remove _id from response
        clinic_data.pop('_id', None)
        return HospitalResponse(**clinic_data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to add clinic: {str(e)}")



# Employee Routes
@router.get("/employee/clinics", response_model=HospitalList)
async def get_employee_clinics(
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
    search: Optional[str] = None,
    type: Optional[HospitalType] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    employee: dict = Depends(get_current_employee),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """Get clinics based on employee location or all if WFH"""
    organization_id = employee.get("organization_id")
    if not organization_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    # Build query
    query = {
        "organization_id": organization_id,
        "status": "active",
        "latitude": {"$exists": True},
        "longitude": {"$exists": True}
    }

    if search:
        query["$or"] = [
            {"name": {"$regex": search, "$options": "i"}},
            {"address": {"$regex": search, "$options": "i"}},
            {"specialties": {"$regex": search, "$options": "i"}}
        ]

    if type:
        query["type"] = type

    # Get employee work mode
    work_mode = None
    is_wfh = False
    if employee.get("employee_id"):
        emp_data = await employee_collection.find_one(
            {"_id": employee["employee_id"]},
            {"work_mode": 1}
        )
        if emp_data:
            work_mode = emp_data.get("work_mode")
            is_wfh = work_mode == "wfh"  # Check if work mode is WFH

    # Get clinics
    clinics = await clinic_collection.find(query).to_list(None)
    user_location = (latitude, longitude)
    clinics_with_distance = []
    
    # Process clinics based on work mode
    if is_wfh:
        # If WFH, include all clinics
        for clinic in clinics:
            if clinic.get("latitude") and clinic.get("longitude"):
                clinic_location = (clinic["latitude"], clinic["longitude"])
                distance = geodesic(user_location, clinic_location).kilometers
                
                clinic['id'] = clinic.pop('_id')
                clinic["distance"] = round(distance * 1000, 2)  # Convert to meters
                clinic["within_range"] = True
                clinics_with_distance.append(clinic)
    else:
        # If not WFH, only include clinics within 100 meters
        # 100 meters = 0.1 kilometers
        MAX_DISTANCE = 0.1
        
        for clinic in clinics:
            if clinic.get("latitude") and clinic.get("longitude"):
                clinic_location = (clinic["latitude"], clinic["longitude"])
                distance = geodesic(user_location, clinic_location).kilometers

                if distance <= MAX_DISTANCE:  # Within 100 meters
                    clinic['id'] = clinic.pop('_id')
                    clinic["distance"] = round(distance * 1000, 2)  # Convert to meters
                    clinic["within_range"] = True
                    clinics_with_distance.append(clinic)

    # Sort by distance and apply pagination
    clinics_with_distance.sort(key=lambda x: x["distance"])
    total_count = len(clinics_with_distance)
    paginated_clinics = clinics_with_distance[skip:skip + limit]

    return HospitalList(
        total_hospitals=total_count,
        work_mode=work_mode,
        coordinates_provided=True,
        hospitals=[HospitalResponse(**clinic) for clinic in paginated_clinics]
    )

@router.post("/employee/clinics/google-place", response_model=HospitalResponse)
async def add_clinic_from_google_employee(
    place_id: str,
    employee: dict = Depends(get_current_employee),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """Add a clinic using Google Places API by employee"""
    organization_id = employee.get("organization_id")
    if not organization_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    # Check for duplicates
    existing = await clinic_collection.find_one({
        "google_place_id": place_id,
        "organization_id": organization_id
    })
    if existing:
        raise HTTPException(status_code=400, detail="Clinic already exists")

    # Fetch details from Google
    details = google_places.get_place_details(place_id)
    if not details:
        raise HTTPException(status_code=404, detail="Place not found")

    # Extract address components
    address_parts = details.get("formatted_address", "").split(",")

    # Generate CLN ID
    clinic_id = generate_random_id("CLN")

    clinic_data = {
        "_id": clinic_id,  # Use the CLN ID as MongoDB _id
        "id": clinic_id,   # Keep this for consistency
        "name": details["name"],
        "address": address_parts[0].strip() if address_parts else details.get("formatted_address", ""),
        "city": address_parts[-3].strip() if len(address_parts) > 3 else "",
        "state": address_parts[-2].strip() if len(address_parts) > 2 else "",
        "country": address_parts[-1].strip() if len(address_parts) > 1 else "India",
        "pincode": "",  # Extract from address if possible
        "latitude": details["geometry"]["location"]["lat"],
        "longitude": details["geometry"]["location"]["lng"],
        "phone": details.get("formatted_phone_number"),
        "website": details.get("website"),
        "google_place_id": place_id,
        "rating": details.get("rating"),
        "organization_id": organization_id,
        "added_by": employee["employee_id"],
        "added_by_role": "employee",
        "created_at": get_current_datetime(),
        "source": "google_places",
        "status": "active",
        "type": HospitalType.HOSPITAL
    }

    try:
        await clinic_collection.insert_one(clinic_data)
        # Remove _id from response
        clinic_data.pop('_id', None)
        return HospitalResponse(**clinic_data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to add clinic: {str(e)}")

@router.post("/admin/clinics/manual", response_model=HospitalResponse)
async def add_clinic_manually_admin(
    request: HospitalManualCreate,
    admin: dict = Depends(get_current_admin),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """Manually add a hospital/clinic/warehouse by admin"""
    organization_id = admin.get("organization_id")
    if not organization_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    # Check for duplicates by name and address
    existing = await clinic_collection.find_one({
        "name": request.name,
        "address": request.address,
        "organization_id": organization_id
    })
    if existing:
        raise HTTPException(status_code=400, detail="A facility with this name and address already exists")

    # Generate CLN ID
    clinic_id = generate_random_id("CLN")

    clinic_data = {
        "_id": clinic_id,  # Use the CLN ID as MongoDB _id
        "id": clinic_id,   # Keep this for consistency
        "name": request.name,
        "address": request.address,
        "city": request.city,
        "state": request.state,
        "country": request.country,
        "pincode": request.pincode,
        "latitude": request.latitude,
        "longitude": request.longitude,
        "phone": request.phone,
        "website": request.website,
        "specialties": request.specialties,
        "organization_id": organization_id,
        "added_by": admin["admin_id"],
        "added_by_role": "admin",
        "created_at": get_current_datetime(),
        "source": "manual",
        "status": "active",
        "type": request.type
    }

    try:
        await clinic_collection.insert_one(clinic_data)
        # Remove _id from response
        clinic_data.pop('_id', None)
        return HospitalResponse(**clinic_data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to add facility: {str(e)}")

@router.post("/employee/clinics/manual", response_model=HospitalResponse)
async def add_clinic_manually_employee(
    request: HospitalManualCreate,
    employee: dict = Depends(get_current_employee),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """Manually add a hospital/clinic/warehouse by employee"""
    organization_id = employee.get("organization_id")
    if not organization_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    # Check for duplicates by name and address
    existing = await clinic_collection.find_one({
        "name": request.name,
        "address": request.address,
        "organization_id": organization_id
    })
    if existing:
        raise HTTPException(status_code=400, detail="A facility with this name and address already exists")

    # Generate CLN ID
    clinic_id = generate_random_id("CLN")

    clinic_data = {
        "_id": clinic_id,  # Use the CLN ID as MongoDB _id
        "id": clinic_id,   # Keep this for consistency
        "name": request.name,
        "address": request.address,
        "city": request.city,
        "state": request.state,
        "country": request.country,
        "pincode": request.pincode,
        "latitude": request.latitude,
        "longitude": request.longitude,
        "phone": request.phone,
        "website": request.website,
        "specialties": request.specialties,
        "organization_id": organization_id,
        "added_by": employee["employee_id"],
        "added_by_role": "employee",
        "created_at": get_current_datetime(),
        "source": "manual",
        "status": "active",
        "type": request.type
    }

    try:
        await clinic_collection.insert_one(clinic_data)
        # Remove _id from response
        clinic_data.pop('_id', None)
        return HospitalResponse(**clinic_data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to add facility: {str(e)}")