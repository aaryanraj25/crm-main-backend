from pydantic import BaseModel, Field
from datetime import date
from typing import List

class ProductModel(BaseModel):
    name:str = Field(..., title="Product Name")
    category: str = Field(..., title = "Product Category")
    quantity: int = Field(..., title = "Product Quantity", ge=0)
    price:int =Field(..., title="Product Price", ge = 0)
    manufacturer: str = Field(..., title ="Manufacturer")
    
    class Config:
        orm_mode = True

class OrderItem(BaseModel):
    name:str = Field(..., title="Product Name")
    category: str = Field(..., title = "Product Category")
    quantity: int = Field(..., title = "Product Quantity", ge=0)
    price:int =Field(..., title="Product Price", ge = 0)
    manufacturer: str = Field(..., title ="Manufacturer")

# Pydantic model for order details
class OrderCreate(BaseModel):
    
    employee_id: str = Field(..., description="Employee who placed the order")
    clinic_hospital_name: str = Field(..., description="Name of the clinic or hospital")
    clinic_hospital_address: str = Field(..., description="Address of the clinic or hospital")
    items: List[OrderItem] = Field(..., description="List of items ordered")
    total_amount: float = Field(..., description="Total amount of the order")
    payment_status: str = Field(..., pattern="^(Paid|Pending)$", description="Payment status (Paid or Pending)")
    delivered_status: str = Field(..., pattern="^(Completed|Pending)$", description="Delivery status")
    order_date: date = Field(..., description="Date when the order was placed")

