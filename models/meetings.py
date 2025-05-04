from pydantic import BaseModel, Field, validator
from typing import Optional, List
from datetime import datetime
from enum import Enum
from models.base import TimeStampedModel
from models.clients import ClientResponse, ClientCreate

class MeetingType(str, Enum):
    FIRST_MEETING = "first_meeting"
    FOLLOW_UP = "follow_up"
    DEMO = "demo"
    NEGOTIATION = "negotiation"
    TRAINING = "training"

class Location(BaseModel):
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)

class ProductInMeeting(BaseModel):
    product_id: str
    name: str
    quantity: int = Field(..., gt=0)
    price: float = Field(..., gt=0)
    total: float

    @validator('total', pre=True, always=True)
    def calculate_total(cls, v, values):
        if 'quantity' in values and 'price' in values:
            return values['quantity'] * values['price']
        return v

class MeetingBase(BaseModel):
    clinic_id: str
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)

class MeetingCreate(MeetingBase):
    client_id: Optional[str] = None
    new_client: Optional[ClientCreate] = None

    @validator('client_id')
    def validate_client_info(cls, v):
        return v

class MeetingResponse(BaseModel):
    id: str = Field(..., alias="_id")
    organization_id: str
    clinic_id: str
    clinic_name: str
    client_id: str
    client: ClientResponse
    check_in_time: datetime
    check_out_time: Optional[datetime] = None
    meeting_type: Optional[MeetingType] = None
    products: Optional[List[ProductInMeeting]] = None
    disbursement_id: Optional[str] = None
    total_amount: Optional[float] = None
    total_quantity: Optional[int] = None
    order_id: Optional[str] = None  # Add this field
    notes: Optional[str] = None
    latitude: float
    longitude: float
    employee_id: str
    created_at: datetime
    disbursement: Optional[dict] = None

class MeetingSummary(BaseModel):
    total_meetings: int
    meetings_by_type: dict
    total_products_disbursed: int
    unique_clients_visited: int
    unique_clinics_visited: int
    date_range: dict

class MeetingCheckOut(BaseModel):
    meeting_type: MeetingType
    products: Optional[List[ProductInMeeting]] = None
    notes: Optional[str] = Field(None, max_length=1000)