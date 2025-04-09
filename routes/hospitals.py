# routes/hospitals.py
from fastapi import APIRouter, HTTPException, Depends, Query
from motor.motor_asyncio import AsyncIOMotorDatabase
from typing import List, Optional
from datetime import datetime, timezone
from geopy.distance import geodesic
import requests
from database import (
    get_database, clinic_collection, visits_collection,
    organization_collection, employee_collection
)
from models.hospitals import (
    HospitalCreate, HospitalResponse, HospitalType,
    HospitalList
)
from security import get_current_admin, get_current_employee
from utils import get_current_datetime

router = APIRouter()

GOOGLE_MAPS_API_KEY = "your_google_maps_api_key"

@router.post("/add", response_model=HospitalResponse)
async def add_hospital(
    hospital: HospitalCreate,
    admin: dict = Depends(get_current_admin),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    organization_id = admin.get("organization_id")
    if not organization_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    # Check if hospital with same name exists in the organization
    existing_hospital = await clinic_collection.find_one({
        "name": hospital.name,
        "organization_id": organization_id
    })
    if existing_hospital:
        raise HTTPException(
            status_code=400,
            detail="Hospital with this name already exists"
        )

    # If coordinates not provided, try to get from address using Google Maps API
    if not hospital.latitude or not hospital.longitude:
        try:
            address = f"{hospital.address}, {hospital.city}, {hospital.state}, {hospital.country}"
            url = f"https://maps.googleapis.com/maps/api/geocode/json?address={address}&key={GOOGLE_MAPS_API_KEY}"
            response = requests.get(url)
            data = response.json()
            
            if data["status"] == "OK":
                location = data["results"][0]["geometry"]["location"]
                hospital.latitude = location["lat"]
                hospital.longitude = location["lng"]
                hospital.google_place_id = data["results"][0]["place_id"]
        except Exception as e:
            print(f"Error getting coordinates: {e}")

    hospital_data = hospital.model_dump()
    hospital_data.update({
        "organization_id": organization_id,
        "added_by": admin["admin_id"],
        "added_by_role": "admin",
        "created_at": get_current_datetime(),
        "source": "database"
    })

    result = await clinic_collection.insert_one(hospital_data)
    hospital_data["_id"] = result.inserted_id

    return HospitalResponse(**hospital_data)

@router.get("/list", response_model=HospitalList)
async def list_hospitals(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    search: Optional[str] = None,
    type: Optional[HospitalType] = None,
    city: Optional[str] = None,
    state: Optional[str] = None,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    radius: Optional[float] = 5.0,  # Default 5 km radius
    employee: dict = Depends(get_current_employee),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    organization_id = employee.get("organization_id")
    if not organization_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    # Build query
    query = {"organization_id": organization_id, "status": "active"}
    
    if search:
        query["$or"] = [
            {"name": {"$regex": search, "$options": "i"}},
            {"address": {"$regex": search, "$options": "i"}},
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

    # Get hospitals
    hospitals = await clinic_collection.find(query) \
        .sort("created_at", -1) \
        .skip(skip) \
        .limit(limit) \
        .to_list(length=limit)

    # Calculate distances if coordinates provided
    if latitude is not None and longitude is not None:
        user_location = (latitude, longitude)
        for hospital in hospitals:
            if hospital.get("latitude") and hospital.get("longitude"):
                hospital_location = (hospital["latitude"], hospital["longitude"])
                distance = geodesic(user_location, hospital_location).kilometers
                hospital["distance"] = round(distance, 2)
                hospital["within_range"] = distance <= radius
            else:
                hospital["distance"] = None
                hospital["within_range"] = None

    # Get work mode for employee
    work_mode = None
    if employee.get("employee_id"):
        emp_data = await employee_collection.find_one(
            {"_id": employee["employee_id"]},
            {"work_mode": 1}
        )
        if emp_data:
            work_mode = emp_data.get("work_mode")

    return HospitalList(
        total_hospitals=total_count,
        work_mode=work_mode,
        coordinates_provided=latitude is not None and longitude is not None,
        hospitals=[HospitalResponse(**h) for h in hospitals]
    )

@router.get("/{hospital_id}", response_model=HospitalResponse)
async def get_hospital(
    hospital_id: str,
    employee: dict = Depends(get_current_employee),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    organization_id = employee.get("organization_id")
    if not organization_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    hospital = await clinic_collection.find_one({
        "_id": hospital_id,
        "organization_id": organization_id
    })

    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    # Get visit statistics
    visit_stats = await visits_collection.aggregate([
        {
            "$match": {
                "hospital_id": hospital_id,
                "organization_id": organization_id
            }
        },
        {
            "$group": {
                "_id": None,
                "total_visits": {"$sum": 1},
                "last_visit": {"$max": "$created_at"}
            }
        }
    ]).to_list(length=1)

    if visit_stats:
        hospital["visit_statistics"] = {
            "total_visits": visit_stats[0]["total_visits"],
            "last_visit": visit_stats[0]["last_visit"]
        }
    else:
        hospital["visit_statistics"] = {
            "total_visits": 0,
            "last_visit": None
        }

    return HospitalResponse(**hospital)

@router.put("/{hospital_id}", response_model=HospitalResponse)
async def update_hospital(
    hospital_id: str,
    hospital: HospitalCreate,
    admin: dict = Depends(get_current_admin),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    organization_id = admin.get("organization_id")
    if not organization_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    existing_hospital = await clinic_collection.find_one({
        "_id": hospital_id,
        "organization_id": organization_id
    })

    if not existing_hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    # Check if name is being changed and if new name exists
    if hospital.name != existing_hospital["name"]:
        name_exists = await clinic_collection.find_one({
            "name": hospital.name,
            "organization_id": organization_id,
            "_id": {"$ne": hospital_id}
        })
        if name_exists:
            raise HTTPException(
                status_code=400,
                detail="Hospital with this name already exists"
            )

    # Update coordinates if address changed
    if (hospital.address != existing_hospital["address"] or
        hospital.city != existing_hospital["city"] or
        hospital.state != existing_hospital["state"]):
        try:
            address = f"{hospital.address}, {hospital.city}, {hospital.state}, {hospital.country}"
            url = f"https://maps.googleapis.com/maps/api/geocode/json?address={address}&key={GOOGLE_MAPS_API_KEY}"
            response = requests.get(url)
            data = response.json()
            
            if data["status"] == "OK":
                location = data["results"][0]["geometry"]["location"]
                hospital.latitude = location["lat"]
                hospital.longitude = location["lng"]
                hospital.google_place_id = data["results"][0]["place_id"]
        except Exception as e:
            print(f"Error updating coordinates: {e}")

    update_data = hospital.model_dump()
    update_data.update({
        "updated_at": get_current_datetime(),
        "updated_by": admin["admin_id"]
    })

    result = await clinic_collection.update_one(
        {"_id": hospital_id, "organization_id": organization_id},
        {"$set": update_data}
    )

    if result.modified_count == 0:
        raise HTTPException(
            status_code=400,
            detail="Hospital not updated"
        )

    updated_hospital = await clinic_collection.find_one({"_id": hospital_id})
    return HospitalResponse(**updated_hospital)

@router.delete("/{hospital_id}")
async def delete_hospital(
    hospital_id: str,
    admin: dict = Depends(get_current_admin),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    organization_id = admin.get("organization_id")
    if not organization_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    # Check if hospital exists
    hospital = await clinic_collection.find_one({
        "_id": hospital_id,
        "organization_id": organization_id
    })

    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    # Check if there are any active visits
    active_visits = await visits_collection.count_documents({
        "hospital_id": hospital_id,
        "status": "active"
    })

    if active_visits > 0:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete hospital with active visits"
        )

    # Soft delete by setting status to inactive
    result = await clinic_collection.update_one(
        {"_id": hospital_id, "organization_id": organization_id},
        {
            "$set": {
                "status": "inactive",
                "deleted_at": get_current_datetime(),
                "deleted_by": admin["admin_id"]
            }
        }
    )

    if result.modified_count == 0:
        raise HTTPException(
            status_code=400,
            detail="Hospital not deleted"
        )

    return {"message": "Hospital deleted successfully"}

@router.get("/stats/overview")
async def get_hospital_stats(
    admin: dict = Depends(get_current_admin),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    organization_id = admin.get("organization_id")
    if not organization_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    # Get hospital statistics
    hospital_stats = await clinic_collection.aggregate([
        {"$match": {"organization_id": organization_id}},
        {
            "$group": {
                "_id": "$type",
                "count": {"$sum": 1},
                "cities": {"$addToSet": "$city"},
                "states": {"$addToSet": "$state"}
            }
        }
    ]).to_list(None)

    # Get visit statistics
    visit_stats = await visits_collection.aggregate([
        {"$match": {"organization_id": organization_id}},
        {
            "$group": {
                "_id": {
                    "year": {"$year": "$created_at"},
                    "month": {"$month": "$created_at"}
                },
                "total_visits": {"$sum": 1},
                "unique_hospitals": {"$addToSet": "$hospital_id"},
                "unique_employees": {"$addToSet": "$employee_id"}
            }
        },
        {"$sort": {"_id.year": -1, "_id.month": -1}},
        {"$limit": 12}
    ]).to_list(None)

    return {
        "hospital_statistics": hospital_stats,
        "visit_trends": visit_stats,
        "total_hospitals": sum(stat["count"] for stat in hospital_stats),
        "total_cities": len(set(city for stat in hospital_stats for city in stat["cities"])),
        "total_states": len(set(state for stat in hospital_stats for state in stat["states"]))
    }

@router.get("/nearby")
async def get_nearby_hospitals(
    latitude: float,
    longitude: float,
    radius: float = Query(5.0, gt=0),  # radius in kilometers
    type: Optional[HospitalType] = None,
    employee: dict = Depends(get_current_employee),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
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
    
    if type:
        query["type"] = type

    # Get all hospitals with coordinates
    hospitals = await clinic_collection.find(query).to_list(None)

    # Calculate distances and filter by radius
    nearby_hospitals = []
    user_location = (latitude, longitude)

    for hospital in hospitals:
        hospital_location = (hospital["latitude"], hospital["longitude"])
        distance = geodesic(user_location, hospital_location).kilometers
        
        if distance <= radius:
            hospital["distance"] = round(distance, 2)
            nearby_hospitals.append(hospital)

    # Sort by distance
    nearby_hospitals.sort(key=lambda x: x["distance"])

    return {
        "total": len(nearby_hospitals),
        "radius": radius,
        "hospitals": [HospitalResponse(**h) for h in nearby_hospitals]
    }

@router.post("/{hospital_id}/rate")
async def rate_hospital(
    hospital_id: str,
    rating: int = Query(..., ge=1, le=5),
    employee: dict = Depends(get_current_employee),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    organization_id = employee.get("organization_id")
    if not organization_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    hospital = await clinic_collection.find_one({
        "_id": hospital_id,
        "organization_id": organization_id
    })

    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    # Update rating
    current_rating = hospital.get("rating", 0)
    current_total_ratings = hospital.get("total_ratings", 0)
    
    new_total_ratings = current_total_ratings + 1
    new_rating = ((current_rating * current_total_ratings) + rating) / new_total_ratings

    await clinic_collection.update_one(
        {"_id": hospital_id},
        {
            "$set": {
                "rating": round(new_rating, 1),
                "total_ratings": new_total_ratings
            },
            "$push": {
                "ratings": {
                    "employee_id": employee["employee_id"],
                    "rating": rating,
                    "created_at": get_current_datetime()
                }
            }
        }
    )

    return {
        "message": "Rating submitted successfully",
        "new_rating": round(new_rating, 1),
        "total_ratings": new_total_ratings
    }