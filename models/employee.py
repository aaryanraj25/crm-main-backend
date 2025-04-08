from pydantic import BaseModel, EmailStr
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
    clinic_id: str  # 🔗 Link to Clinic ID
    designation: Optional[str] = None
    
    
class VisitUpdateRequest(BaseModel):
    clinic_id: str
    latitude: float
    longitude: float
    meeting_outcome: str  # e.g., "Interested", "Not Interested", "Follow-up Required"
    notes: Optional[str] = None
    follow_up_date: Optional[datetime] = None   
    
class VisitModel(BaseModel):
    employee_id: str
    clinic_id: str
    check_in_time: datetime = None
    check_out_time: datetime = None
    time_spent_minutes: int = None
    meeting_outcome: str = None  # "Interested", "Not Interested", "Follow-up Required"
    notes: str = None
    follow_up_date: datetime = None   
    
class CheckInRequest(BaseModel):
    employee_id: str
    clinic_id: str
    latitude: float
    longitude: float    

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

class CheckOutRequest(BaseModel):
    meeting_person: MeetingPerson
    notes: Optional[str]

class Location(BaseModel):
    latitude: float
    longitude: float
    timestamp: datetime   