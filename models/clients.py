from pydantic import BaseModel, EmailStr, Field, validator
from typing import Optional, List
from datetime import datetime
from enum import Enum
from models.base import TimeStampedModel

class ClientCapacity(str, Enum):
    END_USER = "end_user"
    INTENT_PROVIDER = "intent_provider"
    DECISION_MAKER = "decision_maker"
    INFLUENCER = "influencer"
    PURCHASE = "purchase"
    STORE_NAME = "store_name"

class ClientBase(BaseModel):
    name: str = Field(..., min_length=2, description="Client name")
    designation: str = Field(..., description="Client designation")
    department: str = Field(..., description="Client department")
    clinic_id: str = Field(..., description="Clinic ID")
    mobile: str = Field(..., pattern="^[0-9]{10}$", description="10-digit mobile number")
    email: EmailStr = Field(..., description="Email address")
    capacity: ClientCapacity = Field(..., description="Client capacity")

class ClientCreate(ClientBase):
    pass

class ClientUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2)
    designation: Optional[str] = None
    department: Optional[str] = None
    mobile: Optional[str] = Field(None, pattern="^[0-9]{10}$")
    email: Optional[EmailStr] = None
    capacity: Optional[ClientCapacity] = None

class ClientResponse(ClientBase, TimeStampedModel):
    id: str = Field(..., alias="_id")
    clinic_name: str
    organization_id: str
    created_by: str

