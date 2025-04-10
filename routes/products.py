# routes/products.py
from fastapi import APIRouter, HTTPException, Depends, Query
from motor.motor_asyncio import AsyncIOMotorDatabase
from typing import List, Optional
from datetime import datetime, timezone
from database import (
    get_database, product_collection, orders_collection,
    sales_collection, organization_collection
)
from models.products import ProductModel, OrderCreate, OrderResponse
from security import get_current_admin, get_current_employee
from utils import generate_product_id, generate_order_id, get_current_datetime

router = APIRouter()

@router.post("/add")
async def add_product(
    product: ProductModel,
    admin: dict = Depends(get_current_admin)
):
    organization_id = admin.get("organization_id")
    if not organization_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    # Check if product with same name exists in organization
    existing_product = await product_collection.find_one({
        "name": product.name,
        "organization_id": organization_id
    })
    if existing_product:
        raise HTTPException(
            status_code=400,
            detail="Product with this name already exists"
        )

    product_id = generate_product_id()
    product_data = product.model_dump()
    product_data.update({
        "_id": product_id,
        "organization_id": organization_id,
        "created_at": get_current_datetime(),
        "created_by": admin["admin_id"],
        "is_active": True
    })

    await product_collection.insert_one(product_data)

    return {
        "message": "Product added successfully",
        "product_id": product_id
    }

@router.get("/list")
async def list_products(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    category: Optional[str] = None,
    search: Optional[str] = None,
    admin: dict = Depends(get_current_admin)
):
    organization_id = admin.get("organization_id")
    if not organization_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    # Build query
    query = {"organization_id": organization_id}
    if category:
        query["category"] = category
    if search:
        query["$or"] = [
            {"name": {"$regex": search, "$options": "i"}},
            {"manufacturer": {"$regex": search, "$options": "i"}}
        ]

    # Get total count
    total_count = await product_collection.count_documents(query)

    # Get products with pagination
    products = await product_collection.find(query) \
        .sort("created_at", -1) \
        .skip(skip) \
        .limit(limit) \
        .to_list(length=limit)

    return {
        "total": total_count,
        "products": products,
        "page": skip // limit + 1,
        "pages": (total_count + limit - 1) // limit
    }

@router.get("/categories")
async def get_categories(admin: dict = Depends(get_current_admin)):
    organization_id = admin.get("organization_id")
    if not organization_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    categories = await product_collection.distinct(
        "category",
        {"organization_id": organization_id}
    )
    return {"categories": categories}

@router.get("/{product_id}")
async def get_product(
    product_id: str,
    admin: dict = Depends(get_current_admin)
):
    organization_id = admin.get("organization_id")
    if not organization_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    product = await product_collection.find_one({
        "_id": product_id,
        "organization_id": organization_id
    })

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Get sales statistics
    sales_stats = await sales_collection.aggregate([
        {
            "$match": {
                "items.product_id": product_id,
                "organization_id": organization_id
            }
        },
        {
            "$group": {
                "_id": None,
                "total_sales": {"$sum": "$total_amount"},
                "total_quantity": {"$sum": "$items.quantity"}
            }
        }
    ]).to_list(length=1)

    product["sales_statistics"] = sales_stats[0] if sales_stats else {
        "total_sales": 0,
        "total_quantity": 0
    }

    return product

@router.put("/{product_id}")
async def update_product(
    product_id: str,
    product: ProductModel,
    admin: dict = Depends(get_current_admin)
):
    organization_id = admin.get("organization_id")
    if not organization_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    existing_product = await product_collection.find_one({
        "_id": product_id,
        "organization_id": organization_id
    })

    if not existing_product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Check if name is being changed and if new name exists
    if (product.name != existing_product["name"]):
        name_exists = await product_collection.find_one({
            "name": product.name,
            "organization_id": organization_id,
            "_id": {"$ne": product_id}
        })
        if name_exists:
            raise HTTPException(
                status_code=400,
                detail="Product with this name already exists"
            )

    update_data = product.model_dump()
    update_data.update({
        "updated_at": get_current_datetime(),
        "updated_by": admin["admin_id"]
    })

    result = await product_collection.update_one(
        {"_id": product_id, "organization_id": organization_id},
        {"$set": update_data}
    )

    if result.modified_count == 0:
        raise HTTPException(
            status_code=400,
            detail="Product not updated"
        )

    return {"message": "Product updated successfully"}

@router.delete("/{product_id}")
async def delete_product(
    product_id: str,
    admin: dict = Depends(get_current_admin)
):
    organization_id = admin.get("organization_id")
    if not organization_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    # Check if product exists
    product = await product_collection.find_one({
        "_id": product_id,
        "organization_id": organization_id
    })

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Soft delete by setting is_active to False
    result = await product_collection.update_one(
        {"_id": product_id, "organization_id": organization_id},
        {
            "$set": {
                "is_active": False,
                "deleted_at": get_current_datetime(),
                "deleted_by": admin["admin_id"]
            }
        }
    )

    if result.modified_count == 0:
        raise HTTPException(
            status_code=400,
            detail="Product not deleted"
        )

    return {"message": "Product deleted successfully"}

@router.get("/inventory/stats")
async def get_inventory_stats(admin: dict = Depends(get_current_admin)):
    organization_id = admin.get("organization_id")
    if not organization_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    # Get inventory statistics
    pipeline = [
        {"$match": {"organization_id": organization_id, "is_active": True}},
        {
            "$group": {
                "_id": "$category",
                "total_products": {"$sum": 1},
                "total_value": {"$sum": {"$multiply": ["$price", "$quantity"]}},
                "low_stock": {
                    "$sum": {"$cond": [{"$lt": ["$quantity", 10]}, 1, 0]}
                }
            }
        }
    ]

    inventory_stats = await product_collection.aggregate(pipeline).to_list(None)

    # Get sales trends
    sales_pipeline = [
        {"$match": {"organization_id": organization_id}},
        {
            "$group": {
                "_id": {
                    "year": {"$year": "$created_at"},
                    "month": {"$month": "$created_at"}
                },
                "total_sales": {"$sum": "$total_amount"}
            }
        },
        {"$sort": {"_id.year": -1, "_id.month": -1}},
        {"$limit": 12}
    ]

    sales_trends = await sales_collection.aggregate(sales_pipeline).to_list(None)

    return {
        "inventory_stats": inventory_stats,
        "sales_trends": sales_trends
    }

@router.post("/bulk-update")
async def bulk_update_products(
    products: List[ProductModel],
    admin: dict = Depends(get_current_admin)
):
    organization_id = admin.get("organization_id")
    if not organization_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    updated_count = 0
    errors = []

    for product in products:
        try:
            result = await product_collection.update_one(
                {
                    "name": product.name,
                    "organization_id": organization_id
                },
                {
                    "$set": {
                        **product.model_dump(),
                        "updated_at": get_current_datetime(),
                        "updated_by": admin["admin_id"]
                    }
                }
            )
            if result.modified_count > 0:
                updated_count += 1
        except Exception as e:
            errors.append(f"Error updating {product.name}: {str(e)}")

    return {
        "message": f"Updated {updated_count} products",
        "errors": errors if errors else None
    }

@router.get("/orders/list")
async def list_orders(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    status: Optional[str] = None,
    employee: dict = Depends(get_current_employee)
):
    organization_id = employee.get("organization_id")
    if not organization_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    query = {"organization_id": organization_id}
    if status:
        query["status"] = status

    total_count = await orders_collection.count_documents(query)
    orders = await orders_collection.find(query) \
        .sort("created_at", -1) \
        .skip(skip) \
        .limit(limit) \
        .to_list(length=limit)

    return {
        "total": total_count,
        "orders": [OrderResponse(**order) for order in orders],
        "page": skip // limit + 1,
        "pages": (total_count + limit - 1) // limit
    }

@router.get("/orders/{order_id}")
async def get_order(
    order_id: str,
    employee: dict = Depends(get_current_employee)
):
    organization_id = employee.get("organization_id")
    if not organization_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    order = await orders_collection.find_one({
        "_id": order_id,
        "organization_id": organization_id
    })

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    return OrderResponse(**order)

@router.post("/orders/create")
async def create_order(
    order: OrderCreate,
    employee: dict = Depends(get_current_employee)
):
    organization_id = employee.get("organization_id")
    employee_id = employee.get("employee_id")
    
    if not organization_id or not employee_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    # Validate products and check inventory
    for item in order.items:
        product = await product_collection.find_one({
            "name": item.name,
            "organization_id": organization_id,
            "is_active": True
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
        "employee_id": employee_id,
        "created_at": get_current_datetime(),
        "status": "Pending"
    })

    await orders_collection.insert_one(order_data)

    # Update product quantities
    for item in order.items:
        await product_collection.update_one(
            {
                "name": item.name,
                "organization_id": organization_id
            },
            {"$inc": {"quantity": -item.quantity}}
        )

    return {
        "message": "Order created successfully",
        "order_id": order_id
    }