import random
import string
from fastapi import APIRouter, HTTPException, Depends, Query
from motor.motor_asyncio import AsyncIOMotorDatabase
from typing import List, Optional
from datetime import datetime, timedelta, timezone
from database import (
    get_database, employee_collection, admins_collection,
    sales_collection, visits_collection, product_collection,
    organization_collection, orders_collection, attendance_collection,
    wfh_request
)
from dependencies import hash_password
from security import get_current_admin
from services.email_service import send_admin_otp_email, send_employee_invitation, send_admin_invitation
from models.products import OrderResponse
from models.employee import WFHRequestStatus
from utils import (
    generate_employee_id, generate_admin_id,
    generate_sale_id, get_current_datetime
)
from geopy.distance import geodesic

router = APIRouter()

# routes/admin.py
@router.post("/create-employee")
async def create_employee(
    email: str,
    name: str,
    db: AsyncIOMotorDatabase = Depends(get_database),
    current_admin: dict = Depends(get_current_admin)
):
    try:
        # Get admin details from token
        admin_id = current_admin["admin_id"]
        organization_id = current_admin["organization_id"]
        organization = current_admin["organization_name"]

        # Check if employee exists
        existing_employee = await employee_collection.find_one({"email": email})
        if existing_employee:
            raise HTTPException(status_code=400, detail="Employee already exists")

        # Create employee
        employee_id = generate_employee_id()
        employee_data = {
            "_id": employee_id,
            "email": email,
            "name": name,
            "organization_id": organization_id,
            "organization": organization,
            "admin_id": admin_id,
            "created_at": get_current_datetime(),
            "role": "employee"
        }

        await employee_collection.insert_one(employee_data)

        # Send invitation email
        try:
            await send_employee_invitation(email, name, organization)
        except Exception as e:
            print(f"Email error: {e}")

        return {
            "message": "Employee created successfully",
            "employee_id": employee_id
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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
        {"$group": {"_id": None, "totalSales": {"$sum": "$total_amount"}}}  # Changed from $amount to $total_amount
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
                "salesAmount": {"$sum": "$sales_data.total_amount"}  # Changed from amount to total_amount
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

    # Daily sales (past 30 days)
    daily_sales = await sales_collection.aggregate([
        {"$match": {"organization_id": org_id}},
        {
            "$group": {
                "_id": {
                    "year": {"$year": "$date"},
                    "month": {"$month": "$date"},
                    "day": {"$dayOfMonth": "$date"}
                },
                "amount": {"$sum": "$total_amount"}
            }
        },
        {"$sort": {"_id.year": -1, "_id.month": -1, "_id.day": -1}},
        {"$limit": 30}
    ]).to_list(length=None)

    # Weekly sales (past 12 weeks)
    weekly_sales = await sales_collection.aggregate([
        {"$match": {"organization_id": org_id}},
        {
            "$group": {
                "_id": {
                    "year": {"$year": "$date"},
                    "week": {"$week": "$date"}
                },
                "amount": {"$sum": "$total_amount"}
            }
        },
        {"$sort": {"_id.year": -1, "_id.week": -1}},
        {"$limit": 12}
    ]).to_list(length=None)

    # Monthly sales (past 12 months)
    monthly_sales = await sales_collection.aggregate([
        {"$match": {"organization_id": org_id}},
        {
            "$group": {
                "_id": {
                    "year": {"$year": "$date"},
                    "month": {"$month": "$date"}
                },
                "amount": {"$sum": "$total_amount"}
            }
        },
        {"$sort": {"_id.year": -1, "_id.month": -1}},
        {"$limit": 12}
    ]).to_list(length=None)

    # Yearly sales
    yearly_sales = await sales_collection.aggregate([
        {"$match": {"organization_id": org_id}},
        {
            "$group": {
                "_id": {"year": {"$year": "$date"}},
                "amount": {"$sum": "$total_amount"}
            }
        },
        {"$sort": {"_id.year": -1}}
    ]).to_list(length=None)

    return {
        "dailySales": [
            {
                "date": f"{item['_id']['year']}-{item['_id']['month']:02d}-{item['_id']['day']:02d}",
                "amount": item["amount"]
            }
            for item in daily_sales
        ],
        "weeklySales": [
            {
                "year": item["_id"]["year"],
                "week": item["_id"]["week"],
                "amount": item["amount"]
            }
            for item in weekly_sales
        ],
        "monthlySales": [
            {
                "month": datetime(item["_id"]["year"], item["_id"]["month"], 1).strftime("%b"),
                "year": item["_id"]["year"],
                "amount": item["amount"]
            }
            for item in monthly_sales
        ],
        "yearlySales": [
            {"year": item["_id"]["year"], "amount": item["amount"]}
            for item in yearly_sales
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

@router.get("/admin/employees")
async def get_employees_by_admin(
    admin: dict = Depends(get_current_admin),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    organization_id = admin.get("organization_id")
    if not organization_id:
        raise HTTPException(status_code=400, detail="Admin does not belong to an organization")

    employee_collection = db["employee"]
    employees_cursor = employee_collection.find({"organization_id": organization_id})
    employees = await employees_cursor.to_list(length=None)

    if not employees:
        raise HTTPException(status_code=404, detail="No employees found for your organization")

    return {"organization_id": organization_id, "employees": employees}


@router.get("/admin/employee/{employee_id}")
async def get_employee_details(
    employee_id: str,
    start_date: str = Query(None),
    end_date: str = Query(None),
    order_status: str = Query(None, description="Filter by delivered_status: Pending, Rejected, Completed"),
    attendance_status: str = Query(None, description="Filter attendance by status: Active, Inactive"),
    admin: dict = Depends(get_current_admin),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    employee_collection = db["employee"]
    orders_collection = db["orders"]
    sales_collection = db["sales"]
    attendance_collection = db["attendance"]
    client_collection = db["client"]

    # Admin's organization ID
    org_id = admin.get("organization_id")
    if not org_id:
        raise HTTPException(status_code=403, detail="Invalid admin organization")

    # Get employee
    employee = await employee_collection.find_one({"_id": employee_id, "organization_id": org_id})
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found in your organization")

    # Parse date filters
    date_filter = {}
    if start_date and end_date:
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d")
            end = datetime.strptime(end_date, "%Y-%m-%d")
            date_filter = {"$gte": start, "$lte": end}
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

    # Orders filter
    order_query = {"employee_id": employee_id}
    if order_status:
        order_query["delivered_status"] = order_status
    orders = await orders_collection.find(order_query).to_list(length=None)

    # Sales filter
    sales_query = {"employee_id": employee_id}
    if date_filter:
        sales_query["sale_date"] = date_filter  # Use your correct field name
    sales = await sales_collection.find(sales_query).to_list(length=None)

    # Attendance filter
    attendance_query = {"employee_id": employee_id}
    if date_filter:
        attendance_query["date"] = date_filter
    if attendance_status:
        attendance_query["status"] = attendance_status
    attendance = await attendance_collection.find(attendance_query).to_list(length=None)

    # Clients (no filtering)
    client = await client_collection.find({"employee_id": employee_id}).to_list(length=None)

    return {
        "employee": employee,
        "orders": orders,
        "sales": sales,
        "attendance": attendance,
        "clients": client
    }
    



otp_store = {}

def generate_otp(length=6):
    return ''.join(random.choices(string.digits, k=length))

@router.post("/admin/forgot-password/request")
async def request_otp(email: str, db: AsyncIOMotorDatabase = Depends(get_database)):
    admin = await db["admin"].find_one({"email": email})
    if not admin:
        raise HTTPException(status_code=404, detail="Admin not found")

    otp = generate_otp()
    otp_store[email] = {
        "otp": otp,
        "expires": datetime.utcnow() + timedelta(minutes=10)
    }

    await send_admin_otp_email(email,admin["name"], otp)
    return {"message": "OTP sent to email"}

@router.post("/admin/forgot-password/verify")
async def verify_otp(email: str, otp: str):
    otp_data = otp_store.get(email)
    if not otp_data:
        raise HTTPException(status_code=400, detail="No OTP found")

    if otp_data["expires"] < datetime.utcnow():
        otp_store.pop(email, None)
        raise HTTPException(status_code=400, detail="OTP expired")

    if otp_data["otp"] != otp:
        raise HTTPException(status_code=400, detail="Invalid OTP")

    return {"message": "OTP verified"}

@router.post("/admin/forgot-password/reset")
async def reset_password(email: str, new_password: str, db: AsyncIOMotorDatabase = Depends(get_database)):
    if email not in otp_store:
        raise HTTPException(status_code=400, detail="OTP not verified")

    hashed = hash_password(new_password)
    await db["admin"].update_one({"email": email}, {"$set": {"password": hashed}})
    otp_store.pop(email, None)

    return {"message": "Password updated successfully"}