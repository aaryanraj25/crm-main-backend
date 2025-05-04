from enum import Enum
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

class OrderStatus(str, Enum):
    PROSPECTIVE = "prospective"
    PENDING = "pending"
    COMPLETED = "completed"
    REJECTED = "rejected"

class OrderItem(BaseModel):
    product_id: str
    name: str
    quantity: int
    price: float
    total: float

class OrderCreate(BaseModel):
    clinic_id: str
    items: List[OrderItem]
    notes: Optional[str] = None
    total_amount: float
    status: OrderStatus = OrderStatus.PROSPECTIVE

class OrderResponse(BaseModel):
    order_id: str
    clinic_id: str
    employee_id: Optional[str]
    admin_id: Optional[str]
    items: List[OrderItem]
    notes: Optional[str]
    meeting_id: Optional[str] = None
    total_amount: float
    status: OrderStatus
    created_at: datetime
    updated_at: Optional[datetime]
    created_by_name: str
    clinic_name: str


