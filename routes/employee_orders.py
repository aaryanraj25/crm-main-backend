from fastapi import APIRouter, HTTPException, Depends, Query
from typing import Optional, List
from datetime import datetime
from database import (
    orders_collection, clinic_collection,
    product_collection
)
from models.orders import OrderStatus, OrderCreate, OrderResponse
from security import get_current_employee
from utils import generate_order_id, get_current_datetime

router = APIRouter()

@router.get("/employee/orders")
async def get_employee_orders(
    status: Optional[OrderStatus] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    employee: dict = Depends(get_current_employee)
):
    """Get all orders for the employee"""
    employee_id = employee.get("employee_id")
    organization_id = employee.get("organization_id")

    # Build query
    query = {
        "organization_id": organization_id,
        "employee_id": employee_id
    }
    if status:
        query["status"] = status

    # Date range filter
    if start_date and end_date:
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d")
            end = datetime.strptime(end_date, "%Y-%m-%d")
            query["created_at"] = {"$gte": start, "$lte": end}
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Invalid date format. Use YYYY-MM-DD"
            )

    # Get total count
    total_count = await orders_collection.count_documents(query)

    # Get orders with clinic details
    pipeline = [
        {"$match": query},
        {
            "$lookup": {
                "from": "clinic",
                "localField": "clinic_id",
                "foreignField": "_id",
                "as": "clinic"
            }
        },
        {"$unwind": {"path": "$clinic", "preserveNullAndEmptyArrays": True}},
        {
            "$project": {
                "order_id": "$_id",
                "clinic_id": 1,
                "clinic_name": "$clinic.name",
                "items": 1,
                "notes": 1,
                "total_amount": 1,
                "status": 1,
                "created_at": 1,
                "updated_at": 1
            }
        },
        {"$sort": {"created_at": -1}},
        {"$skip": skip},
        {"$limit": limit}
    ]

    orders = await orders_collection.aggregate(pipeline).to_list(length=None)

    return {
        "total": total_count,
        "orders": orders,
        "page": skip // limit + 1,
        "pages": (total_count + limit - 1) // limit
    }

@router.post("/employee/orders")
async def create_employee_order(
    order: OrderCreate,
    employee: dict = Depends(get_current_employee)
):
    """Create a new order as employee"""
    employee_id = employee.get("employee_id")
    organization_id = employee.get("organization_id")

    # Validate clinic
    clinic = await clinic_collection.find_one({
        "_id": order.clinic_id,
        "organization_id": organization_id
    })
    if not clinic:
        raise HTTPException(status_code=404, detail="Clinic not found")

    # Validate products
    for item in order.items:
        product = await product_collection.find_one({
            "_id": item.product_id,
            "organization_id": organization_id
        })
        if not product:
            raise HTTPException(
                status_code=404,
                detail=f"Product not found: {item.name}"
            )

    order_id = generate_order_id()
    order_data = order.model_dump()
    order_data.update({
        "_id": order_id,
        "organization_id": organization_id,
        "employee_id": employee_id,
        "created_at": get_current_datetime(),
        "status": OrderStatus.PROSPECTIVE
    })

    await orders_collection.insert_one(order_data)

    return {
        "message": "Order created successfully",
        "order_id": order_id
    }

@router.put("/employee/orders/{order_id}")
async def update_employee_order(
    order_id: str,
    order: OrderCreate,
    employee: dict = Depends(get_current_employee)
):
    """Update an existing order"""
    employee_id = employee.get("employee_id")
    organization_id = employee.get("organization_id")

    existing_order = await orders_collection.find_one({
        "_id": order_id,
        "employee_id": employee_id,
        "organization_id": organization_id
    })

    if not existing_order:
        raise HTTPException(status_code=404, detail="Order not found")

    if existing_order["status"] not in [OrderStatus.PROSPECTIVE, OrderStatus.PENDING]:
        raise HTTPException(
            status_code=400,
            detail="Cannot update completed or rejected orders"
        )

    update_data = order.model_dump()
    update_data.update({
        "updated_at": get_current_datetime(),
        "status": OrderStatus.PENDING
    })

    result = await orders_collection.update_one(
        {"_id": order_id},
        {"$set": update_data}
    )

    if result.modified_count == 0:
        raise HTTPException(
            status_code=400,
            detail="Failed to update order"
        )

    return {"message": "Order updated successfully"}

@router.get("/employee/clinics")
async def get_employee_clinics(
    search: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    employee: dict = Depends(get_current_employee)
):
    """Get all clinics for the employee"""
    organization_id = employee.get("organization_id")

    # Build query
    query = {"organization_id": organization_id, "status": "active"}
    if search:
        query["$or"] = [
            {"name": {"$regex": search, "$options": "i"}},
            {"address": {"$regex": search, "$options": "i"}}
        ]

    # Get total count
    total_count = await clinic_collection.count_documents(query)

    # Get clinics
    clinics = await clinic_collection.find(query) \
        .sort("name", 1) \
        .skip(skip) \
        .limit(limit) \
        .to_list(length=limit)

    return {
        "total": total_count,
        "clinics": clinics,
        "page": skip // limit + 1,
        "pages": (total_count + limit - 1) // limit
    }