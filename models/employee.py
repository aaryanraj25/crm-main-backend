from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import datetime
from enum import Enum

class EmployeeCreateRequest(BaseModel):
    name: str
    email: EmailStr

class ClinicModel(BaseModel):
    name: str
    address: str
    city: str
    state: str
    contact_person: str
    contact_number: str
    email: Optional[EmailStr] = None
    specialization: Optional[str] = None
    latitude: float
    longitude: float

class ClientModel(BaseModel):
    name: str
    contact_number: str
    email: Optional[EmailStr] = None
    clinic_id: str
    designation: Optional[str] = None

class WFHRequestStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"

class WFHRequest(BaseModel):
    date: datetime
    reason: str
    status: WFHRequestStatus = WFHRequestStatus.PENDING

class MeetingPerson(BaseModel):
    name: str
    designation: str
    contact: Optional[str]

class CheckInRequest(BaseModel):
    clinic_id: str
    latitude: float
    longitude: float

class CheckOutRequest(BaseModel):
    meeting_person: MeetingPerson
    notes: Optional[str]

class Location(BaseModel):
    latitude: float
    longitude: float
    timestamp: datetime