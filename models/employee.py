from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime

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
    latitude: float  # New field
    longitude: float  # New field 
    
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