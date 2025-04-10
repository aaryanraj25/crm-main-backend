# models/products.py
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime

class ProductModel(BaseModel):
    name: str
    category: str
    quantity: int = Field(ge=0)  # quantity can't be negative
    price: float = Field(ge=0)   # price can't be negative
    manufacturer: str

class OrderItem(BaseModel):
    product_id: str
    name: str
    quantity: int = Field(ge=1)  # minimum 1 item
    price: float
    total_amount: float

class OrderCreate(BaseModel):
    clinic_hospital_name: str
    clinic_hospital_address: str
    items: List[OrderItem]
    total_amount: float
    payment_status: str = "Pending"  # Pending/Paid
    delivered_status: str = "Pending"  # Pending/Completed
    order_date: datetime

class OrderResponse(BaseModel):
    order_id: str
    employee_id: str
    clinic_hospital_name: str
    clinic_hospital_address: str
    items: List[OrderItem]
    total_amount: float
    payment_status: str
    delivered_status: str
    order_date: datetime