from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum

class HospitalType(str, Enum):
    HOSPITAL = "hospital"
    CLINIC = "clinic"
    NURSING_HOME = "nursing_home"
    DIAGNOSTIC = "diagnostic"
    PHARMACY = "pharmacy"
    OTHER = "other"

class HospitalCreate(BaseModel):
    name: str = Field(..., min_length=2)
    address: str
    city: str
    state: str
    country: str
    pincode: str
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    website: Optional[str] = None
    latitude: Optional[float] = Field(None, ge=-90, le=90)
    longitude: Optional[float] = Field(None, ge=-180, le=180)
    specialties: Optional[List[str]] = []
    type: Optional[HospitalType] = HospitalType.HOSPITAL
    status: str = "active"

class HospitalResponse(HospitalCreate):
    id: str
    organization_id: str
    added_by: str
    added_by_role: str
    created_at: datetime
    updated_at: Optional[datetime] = None
    google_place_id: Optional[str] = None
    rating: Optional[float] = None
    total_ratings: Optional[int] = 0
    distance: Optional[float] = None
    within_range: Optional[bool] = None
    source: str = "database"

class HospitalList(BaseModel):
    total_hospitals: int
    work_mode: Optional[str]
    coordinates_provided: Optional[bool]
    hospitals: List[HospitalResponse]