from fastapi import APIRouter, HTTPException, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from typing import List, Optional
from datetime import datetime, timezone
from database import (
    get_database, employee_collection, admins_collection,
    sales_collection, visits_collection, product_collection,
    organization_collection, orders_collection, attendance_collection,
    wfh_request
)
from security import get_current_admin
from services.email_service import send_employee_invitation, send_admin_invitation
from models.products import OrderResponse
from models.employee import WFHRequestStatus
from utils import (
    generate_employee_id, generate_admin_id,
    generate_sale_id, get_current_datetime
)
from geopy.distance import geodesic

router = APIRouter()

@router.post("/create-employee")
async def create_employee(
    email: str,
    name: str,
    db: AsyncIOMotorDatabase = Depends(get_database),
    admin: dict = Depends(get_current_admin)
):
    admin_id = admin["admin_id"]
    admin_data = await admins_collection.find_one({"_id": admin_id})

    if not admin_data:
        raise HTTPException(status_code=404, detail="Admin not found")

    org_id = admin_data.get("organization_id")
    if not org_id:
        raise HTTPException(status_code=400, detail="Organization ID missing")

    organization_data = await organization_collection.find_one({"_id": org_id})
    if not organization_data:
        raise HTTPException(status_code=404, detail="Organization not found")

    org_name = organization_data.get("name")
    emp_limit = organization_data.get("emp_count", 0)

    current_emp_count = await employee_collection.count_documents({"organization_id": org_id})
    if current_emp_count >= emp_limit:
        raise HTTPException(status_code=403, detail=f"Employee limit reached ({emp_limit})")

    existing_employee = await employee_collection.find_one({"email": email})
    if existing_employee:
        raise HTTPException(status_code=400, detail="Employee already exists")

    employee_id = generate_employee_id()

    employee_data = {
        "_id": employee_id,
        "email": email,
        "name": name,
        "organization_id": org_id,
        "organization": org_name,
        "created_at": get_current_datetime(),
        "admin_id": admin_id,
        "role": "employee"
    }

    await employee_collection.insert_one(employee_data)
    await organization_collection.update_one(
        {"_id": org_id},
        {"$inc": {"total_employees": 1}}
    )

    await send_employee_invitation(email, name, org_name)

    return {
        "message": "Employee created successfully",
        "employee_id": employee_id,
        "organization_id": org_id,
        "organization_name": org_name,
        "created_at": employee_data["created_at"]
    }

@router.get("/employee-location/{employee_id}")
async def get_employee_location(
    employee_id: str,
    admin: dict = Depends(get_current_admin)
):
    organization_id = admin.get("organization_id")
    if not organization_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    employee = await employee_collection.find_one(
        {"_id": employee_id, "organization_id": organization_id},
        {"location": 1, "name": 1}
    )

    if not employee:
        raise HTTPException(
            status_code=404,
            detail="Employee not found or does not belong to your organization"
        )

    location = employee.get("location")
    if not location:
        raise HTTPException(status_code=404, detail="Location not available")

    return {
        "employee_name": employee.get("name"),
        "location": {
            "latitude": location.get("latitude"),
            "longitude": location.get("longitude"),
            "updated_at": location.get("updated_at")
        },
        "google_maps_url": f"https://www.google.com/maps?q={location.get('latitude')},{location.get('longitude')}"
    }

@router.get("/organization-stats")
async def get_organization_stats(
    db: AsyncIOMotorDatabase = Depends(get_database),
    admin: dict = Depends(get_current_admin)
):
    org_id = admin.get("organization_id")
    if not org_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    total_sales = await sales_collection.aggregate([
        {"$match": {"organization_id": org_id}},
        {"$group": {"_id": None, "totalSales": {"$sum": "$amount"}}}
    ]).to_list(length=1)

    total_visits = await visits_collection.count_documents({"organization_id": org_id})
    total_meetings = await visits_collection.count_documents({
        "organization_id": org_id,
        "type": "meeting"
    })

    return {
        "totalSales": total_sales[0]["totalSales"] if total_sales else 0,
        "totalVisits": total_visits,
        "totalMeetings": total_meetings
    }

@router.get("/employee-performance")
async def get_employee_performance(
    db: AsyncIOMotorDatabase = Depends(get_database),
    admin: dict = Depends(get_current_admin)
):
    org_id = admin.get("organization_id")
    if not org_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    employees = await employee_collection.aggregate([
        {"$match": {"organization_id": org_id}},
        {
            "$lookup": {
                "from": "sales",
                "localField": "_id",
                "foreignField": "employee_id",
                "as": "sales_data"
            }
        },
        {
            "$lookup": {
                "from": "visits",
                "localField": "_id",
                "foreignField": "employee_id",
                "as": "visit_data"
            }
        },
        {
            "$project": {
                "employeeId": "$_id",
                "name": 1,
                "salesAmount": {"$sum": "$sales_data.amount"},
                "clientsCount": {"$size": "$sales_data"},
                "hospitalVisits": {"$size": "$visit_data"}
            }
        }
    ]).to_list(length=None)

    return {"employeePerformance": employees}

@router.get("/top-employees")
async def get_top_employees(
    db: AsyncIOMotorDatabase = Depends(get_database),
    admin: dict = Depends(get_current_admin)
):
    org_id = admin.get("organization_id")
    if not org_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    top_employees = await employee_collection.aggregate([
        {"$match": {"organization_id": org_id}},
        {
            "$lookup": {
                "from": "sales",
                "localField": "_id",
                "foreignField": "employee_id",
                "as": "sales_data"
            }
        },
        {
            "$project": {
                "employeeId": "$_id",
                "name": 1,
                "salesAmount": {"$sum": "$sales_data.amount"}
            }
        },
        {"$sort": {"salesAmount": -1}},
        {"$limit": 3}
    ]).to_list(length=3)

    return {"topEmployees": top_employees}

@router.get("/top-products")
async def get_top_products(
    db: AsyncIOMotorDatabase = Depends(get_database),
    admin: dict = Depends(get_current_admin)
):
    org_id = admin.get("organization_id")
    if not org_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    top_products = await product_collection.aggregate([
        {"$match": {"organization_id": org_id}},
        {
            "$lookup": {
                "from": "sales",
                "localField": "_id",
                "foreignField": "product_id",
                "as": "sales_data"
            }
        },
        {
            "$project": {
                "productId": "$_id",
                "name": 1,
                "quantity": {"$sum": "$sales_data.quantity"},
                "sales": {"$sum": "$sales_data.amount"}
            }
        },
        {"$sort": {"sales": -1}},
        {"$limit": 3}
    ]).to_list(length=3)

    return {"topProducts": top_products}

@router.get("/sales-trends")
async def get_sales_trends(
    db: AsyncIOMotorDatabase = Depends(get_database),
    admin: dict = Depends(get_current_admin)
):
    org_id = admin.get("organization_id")
    if not org_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    yearly_sales = await sales_collection.aggregate([
        {"$match": {"organization_id": org_id}},
        {
            "$group": {
                "_id": {"year": {"$year": "$date"}},
                "amount": {"$sum": "$amount"}
            }
        },
        {"$sort": {"_id.year": -1}}
    ]).to_list(length=None)

    monthly_sales = await sales_collection.aggregate([
        {"$match": {"organization_id": org_id}},
        {
            "$group": {
                "_id": {
                    "year": {"$year": "$date"},
                    "month": {"$month": "$date"}
                },
                "amount": {"$sum": "$amount"}
            }
        },
        {"$sort": {"_id.year": -1, "_id.month": -1}}
    ]).to_list(length=None)

    return {
        "yearlySales": [
            {"year": item["_id"]["year"], "amount": item["amount"]}
            for item in yearly_sales
        ],
        "monthlySales": [
            {
                "month": datetime(2025, item["_id"]["month"], 1).strftime("%b"),
                "year": item["_id"]["year"],
                "amount": item["amount"]
            }
            for item in monthly_sales
        ]
    }

@router.get("/get_orders", response_model=List[OrderResponse])
async def get_orders_by_admin(
    db: AsyncIOMotorDatabase = Depends(get_database),
    current_admin: dict = Depends(get_current_admin)
):
    organization_id = current_admin["organization_id"]

    orders = await orders_collection.find(
        {"organization_id": organization_id}
    ).to_list(length=100)

    if not orders:
        raise HTTPException(
            status_code=404,
            detail="No orders found for this organization"
        )

    return [
        OrderResponse(
            order_id=order["_id"],
            employee_id=order["employee_id"],
            clinic_hospital_name=order["clinic_hospital_name"],
            clinic_hospital_address=order["clinic_hospital_address"],
            items=order["items"],
            total_amount=order["total_amount"],
            payment_status=order["payment_status"],
            delivered_status=order["delivered_status"],
            order_date=order["order_date"]
        ) for order in orders
    ]

@router.put("/orders/{order_id}/complete")
async def complete_order(
    order_id: str,
    admin: dict = Depends(get_current_admin)
):
    organization_id = admin.get("organization_id")
    if not organization_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    order = await orders_collection.find_one({"_id": order_id})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # Update order status
    await orders_collection.update_one(
        {"_id": order_id},
        {
            "$set": {
                "status": "Completed",
                "payment_status": "Completed",
                "delivered_status": "Completed",
                "completed_at": get_current_datetime()
            }
        }
    )

    # Create sale record
    sale_id = generate_sale_id()
    await sales_collection.insert_one({
        "_id": sale_id,
        "order_id": order_id,
        "organization_id": organization_id,
        "employee_id": order["employee_id"],
        "total_amount": order["total_amount"],
        "date": get_current_datetime(),
        "items": order["items"]
    })

    # Update product quantities
    for item in order["items"]:
        await product_collection.update_one(
            {
                "name": item["name"],
                "organization_id": organization_id
            },
            {"$inc": {"quantity": -item["quantity"]}}
        )

    return {"message": "Order completed successfully"}

@router.get("/wfh-requests")
async def get_wfh_requests(
    status: Optional[WFHRequestStatus] = None,
    admin: dict = Depends(get_current_admin)
):
    organization_id = admin.get("organization_id")
    if not organization_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    query = {"organization_id": organization_id}
    if status:
        query["status"] = status

    requests = await wfh_request.aggregate([
        {"$match": query},
        {
            "$lookup": {
                "from": "employees",
                "localField": "employee_id",
                "foreignField": "_id",
                "as": "employee"
            }
        },
        {"$unwind": "$employee"}
    ]).to_list(None)

    return {"requests": requests}

@router.put("/wfh-requests/{request_id}")
async def update_wfh_request_status(
    request_id: str,
    status: WFHRequestStatus,
    admin: dict = Depends(get_current_admin)
):
    organization_id = admin.get("organization_id")
    if not organization_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    result = await wfh_request.update_one(
        {"_id": request_id, "organization_id": organization_id},
        {
            "$set": {
                "status": status.value,
                "updated_at": get_current_datetime(),
                "updated_by": admin["admin_id"]
            }
        }
    )

    if result.modified_count == 0:
        raise HTTPException(
            status_code=404,
            detail="WFH request not found or not updated"
        )

    return {"message": f"WFH request {status.value} successfully"}

@router.post("/admin/create-admin")
async def create_admin(
    email: str,
    name: str,
    phone: str,
    db: AsyncIOMotorDatabase = Depends(get_database),
    admin: dict = Depends(get_current_admin)
):
    admin_data = await admins_collection.find_one({"_id": admin["admin_id"]})
    if not admin_data:
        raise HTTPException(status_code=404, detail="Admin not found")

    org_id = admin_data.get("organization_id")
    org_name = admin_data.get("organization")

    if not org_id or not org_name:
        raise HTTPException(
            status_code=400,
            detail="Organization details missing for admin"
        )

    existing_admin = await admins_collection.find_one({"email": email})
    if existing_admin:
        raise HTTPException(status_code=400, detail="Admin already exists")

    new_admin_id = generate_admin_id()

    new_admin_data = {
        "_id": new_admin_id,
        "email": email,
        "name": name,
        "phone": phone,
        "organization_id": org_id,
        "organization": org_name,
        "created_at": get_current_datetime(),
        "created_by_admin_id": admin["admin_id"],
        "role": "admin",
        "is_verified": True
    }

    await admins_collection.insert_one(new_admin_data)
    await send_admin_invitation(email, name, org_name)

    return {
        "message": "Admin created successfully",
        "admin_id": new_admin_id,
        "organization_id": org_id,
        "organization_name": org_name,
        "created_at": new_admin_data["created_at"]
    }

@router.get("/employee-tracking")
async def get_employee_tracking(
    date: Optional[str] = None,
    employee_id: Optional[str] = None,
    admin: dict = Depends(get_current_admin)
):
    organization_id = admin.get("organization_id")
    if not organization_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    query = {"organization_id": organization_id}
    if date:
        query["date"] = datetime.strptime(date, "%Y-%m-%d")
    if employee_id:
        query["employee_id"] = employee_id

    visits = await visits_collection.find(query).to_list(None)
    tracking_data = []

    for visit in visits:
        total_distance = 0
        locations = visit.get("locations", [])

        for i in range(len(locations) - 1):
            point1 = (locations[i]["latitude"], locations[i]["longitude"])
            point2 = (locations[i + 1]["latitude"], locations[i + 1]["longitude"])
            total_distance += geodesic(point1, point2).kilometers

        tracking_data.append({
            "visit_id": visit["_id"],
            "employee_id": visit["employee_id"],
            "hospital_id": visit["hospital_id"],
            "check_in_time": visit["check_in_time"],
            "check_out_time": visit.get("check_out_time"),
            "total_distance": round(total_distance, 2),
            "locations": locations
        })

    return {"tracking_data": tracking_data}