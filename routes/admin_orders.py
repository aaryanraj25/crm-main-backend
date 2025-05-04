from fastapi import APIRouter, HTTPException, Depends, Query
from typing import Optional, List
from datetime import datetime
from database import (
    orders_collection, sales_collection,
    product_collection, employee_collection,
    clinic_collection
)
from models.orders import OrderStatus, OrderCreate, OrderResponse
from security import get_current_admin
from utils import generate_order_id, get_current_datetime, generate_sale_id

router = APIRouter()

@router.get("/admin/orders")
async def get_all_orders(
    status: Optional[OrderStatus] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    employee_id: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    admin: dict = Depends(get_current_admin)
):
    """Get all orders with filters"""
    organization_id = admin.get("organization_id")

    # Build query
    query = {"organization_id": organization_id}
    if status:
        query["status"] = status
    if employee_id:
        query["employee_id"] = employee_id

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

    # Get orders with employee/admin details
    pipeline = [
        {"$match": query},
        {
            "$lookup": {
                "from": "employee",
                "localField": "employee_id",
                "foreignField": "_id",
                "as": "employee"
            }
        },
        {
            "$lookup": {
                "from": "admin",
                "localField": "admin_id",
                "foreignField": "_id",
                "as": "admin"
            }
        },
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
                "updated_at": 1,
                "employee_id": 1,
                "admin_id": 1,
                "created_by_name": {
                    "$cond": {
                        "if": {"$gt": [{"$size": "$employee"}, 0]},
                        "then": {"$arrayElemAt": ["$employee.name", 0]},
                        "else": {
                            "$cond": {
                                "if": {"$gt": [{"$size": "$admin"}, 0]},
                                "then": {"$arrayElemAt": ["$admin.name", 0]},
                                "else": "Unknown"
                            }
                        }
                    }
                }
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

@router.post("/admin/orders")
async def create_admin_order(
    order: OrderCreate,
    admin: dict = Depends(get_current_admin)
):
    """Create a new order as admin"""
    organization_id = admin.get("organization_id")
    admin_id = admin.get("admin_id")

    # Validate clinic
    clinic = await clinic_collection.find_one({
        "_id": order.clinic_id,
        "organization_id": organization_id
    })
    if not clinic:
        raise HTTPException(status_code=404, detail="Clinic not found")

    # Validate products and check inventory
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
        if product["quantity"] < item.quantity:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient inventory for {item.name}"
            )

    order_id = generate_order_id()
    order_data = order.model_dump()
    order_data.update({
        "_id": order_id,
        "organization_id": organization_id,
        "admin_id": admin_id,
        "created_at": get_current_datetime(),
        "status": OrderStatus.PENDING
    })

    await orders_collection.insert_one(order_data)

    return {
        "message": "Order created successfully",
        "order_id": order_id
    }

@router.put("/admin/orders/{order_id}/status")
async def update_order_status(
    order_id: str,
    status: OrderStatus,
    admin: dict = Depends(get_current_admin)
):
    """Update order status"""
    organization_id = admin.get("organization_id")

    order = await orders_collection.find_one({
        "_id": order_id,
        "organization_id": organization_id
    })
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    update_data = {
        "status": status,
        "updated_at": get_current_datetime(),
        "updated_by": admin["admin_id"]
    }

    if status == OrderStatus.COMPLETED:
        # Create sale record and update inventory
        sale_data = {
            "_id": generate_sale_id(),
            "order_id": order_id,
            "organization_id": organization_id,
            "employee_id": order.get("employee_id"),
            "admin_id": order.get("admin_id"),
            "clinic_id": order["clinic_id"],
            "items": order["items"],
            "total_amount": order["total_amount"],
            "created_at": get_current_datetime()
        }
        await sales_collection.insert_one(sale_data)

        # Update product inventory
        for item in order["items"]:
            await product_collection.update_one(
                {"_id": item["product_id"]},
                {"$inc": {"quantity": -item["quantity"]}}
            )

    result = await orders_collection.update_one(
        {"_id": order_id},
        {"$set": update_data}
    )

    if result.modified_count == 0:
        raise HTTPException(
            status_code=400,
            detail="Failed to update order status"
        )

    return {"message": f"Order status updated to {status}"}

@router.get("/admin/orders/{order_id}")
async def get_order_details(
    order_id: str,
    admin: dict = Depends(get_current_admin)
):
    """Get detailed order information"""
    organization_id = admin.get("organization_id")

    pipeline = [
        {"$match": {"_id": order_id, "organization_id": organization_id}},
        {
            "$lookup": {
                "from": "employee",
                "localField": "employee_id",
                "foreignField": "_id",
                "as": "employee"
            }
        },
        {
            "$lookup": {
                "from": "admin",
                "localField": "admin_id",
                "foreignField": "_id",
                "as": "admin"
            }
        },
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
                "clinic_address": "$clinic.address",
                "items": 1,
                "notes": 1,
                "total_amount": 1,
                "status": 1,
                "created_at": 1,
                "updated_at": 1,
                "employee_details": {"$arrayElemAt": ["$employee", 0]},
                "admin_details": {"$arrayElemAt": ["$admin", 0]}
            }
        }
    ]

    order = await orders_collection.aggregate(pipeline).to_list(length=1)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    return order[0]