from fastapi import APIRouter, HTTPException, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from typing import List, Optional
from database import get_database, employee_collection, admins_collection, sales_collection, visits_collection, product_collection, organization_collection, orders_collection, attendance_collection, wfh_request
from security import get_current_admin
from datetime import datetime, timezone
from bson import ObjectId
from services.email_service import send_employee_invitation, send_admin_invitation
from models.products import OrderResponse
from models.employee import WFHRequestStatus
from geopy.distance import geodesic 
from utils import generate_random_id, generate_admin_id, generate_employee_id, generate_sale_id





router = APIRouter()

def convert_objectid_to_str(document):
    """Recursively converts ObjectId fields in a document to strings."""
    if isinstance(document, dict):
        for key, value in document.items():
            if isinstance(value, ObjectId):
                document[key] = str(value)
            elif isinstance(value, list):  
                document[key] = [str(v) if isinstance(v, ObjectId) else v for v in value]
    return document


@router.post("/create-employee")
async def create_employee(
    email: str,
    name: str,
    db: AsyncIOMotorDatabase = Depends(get_database),
    admin: dict = Depends(get_current_admin)
):
    

    admin_id = admin["admin_id"]  # Already a custom string
    admin_data = await admins_collection.find_one({"_id": admin_id})

    if not admin_data:
        raise HTTPException(status_code=404, detail="Admin not found")

    org_id = admin_data.get("organization_id")
    if not org_id:
        raise HTTPException(status_code=400, detail="Organization ID missing")

    organization_data = await db["organizations"].find_one({"_id": org_id})
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
        "created_at": datetime.now(timezone.utc),
        "admin_id": admin_id,
        "role": "employee"
    }

    await employee_collection.insert_one(employee_data)

    await db["organizations"].update_one(
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
    admin: dict = Depends(get_current_admin),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    organization_id = admin.get("organization_id")

    if not organization_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    employee = await employee_collection.find_one(
        {"_id": employee_id, "organization_id": organization_id},
        {"location": 1, "name": 1}
    )

    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found or does not belong to your organization")

    location = employee.get("location")
    if not location:
        raise HTTPException(status_code=404, detail="Location not available")

    latitude = location.get("latitude")
    longitude = location.get("longitude")

    return {
        "employee_name": employee.get("name"),
        "location": {
            "latitude": latitude,
            "longitude": longitude,
            "updated_at": location.get("updated_at")
        },
        "google_maps_url": f"https://www.google.com/maps?q={latitude},{longitude}"
    }

    
    
@router.get("/employees")
async def get_all_employees(
    admin: dict = Depends(get_current_admin),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    organization_id = admin.get("organization_id")
    if not organization_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    employees_cursor = employee_collection.find(
        {"organization_id": organization_id},
        {"password": 0}
    )

    employees = await employees_cursor.to_list(length=None)

    return {
        "total_employees": len(employees),
        "employees": employees
    }



@router.get("/organization-stats")
async def get_organization_stats(
    db: AsyncIOMotorDatabase = Depends(get_database),
    admin: dict = Depends(get_current_admin)
):
    """Get organization-wide stats for sales, visits, and meetings."""
    org_id = admin.get("organization_id")
    if not org_id:
        raise HTTPException(status_code=401, detail="Invalid token or organization ID missing")

    total_sales = await sales_collection.aggregate([
        {"$match": {"organization_id": org_id}},
        {"$group": {"_id": None, "totalSales": {"$sum": "$amount"}}}
    ]).to_list(length=1)

    total_visits = await visits_collection.count_documents({"organization_id": org_id})
    total_meetings = await visits_collection.count_documents({"organization_id": org_id, "type": "meeting"})

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
    """Get performance metrics for employees in the organization."""
    org_id = admin.get("organization_id")
    if not org_id:
        raise HTTPException(status_code=401, detail="Invalid token or organization ID missing")

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
    """Get top 3 employees based on sales."""
    org_id = admin.get("organization_id")
    if not org_id:
        raise HTTPException(status_code=401, detail="Invalid token or organization ID missing")

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
    """Get top 3 products based on sales."""
    org_id = admin.get("organization_id")
    if not org_id:
        raise HTTPException(status_code=401, detail="Invalid token or organization ID missing")

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
    """Get yearly and monthly sales trends."""
    org_id = admin.get("organization_id")
    if not org_id:
        raise HTTPException(status_code=401, detail="Invalid token or organization ID missing")

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

    formatted_yearly_sales = [
        {"year": item["_id"]["year"], "amount": item["amount"]}
        for item in yearly_sales
    ]

    formatted_monthly_sales = [
        {
            "month": datetime(2025, item["_id"]["month"], 1).strftime("%b"),
            "year": item["_id"]["year"],
            "amount": item["amount"]
        }
        for item in monthly_sales
    ]

    return {
        "yearlySales": formatted_yearly_sales,
        "monthlySales": formatted_monthly_sales
    }

    
@router.get("/organizations")
async def get_organizations(db: AsyncIOMotorDatabase = Depends(get_database)):
    organizations = await organization_collection.find().to_list(length=None)

    if not organizations:
        raise HTTPException(status_code=404, detail="No organizations found")

    return [
        {
            "organization_id": org["_id"],
            "name": org["name"],
            "address": org["address"],
            "contact_person": org["contact_person"],
            "contact_email": org["contact_email"],
            "contact_number": org["contact_number"],
            "total_employees": org["total_employees"]
        }
        for org in organizations
    ]

@router.post("/admin/create-admin")
async def create_admin(
    email: str,
    name: str,
    phone_no: str,
    db: AsyncIOMotorDatabase = Depends(get_database),
    admin: dict = Depends(get_current_admin)
):
    

    # Ensure admin exists
    admin_data = await admins_collection.find_one({"_id": admin["admin_id"]})
    if not admin_data:
        raise HTTPException(status_code=404, detail="Admin not found")

    org_id = admin_data.get("organization_id")
    org_name = admin_data.get("organization")

    if not org_id or not org_name:
        raise HTTPException(status_code=400, detail="Organization details missing for admin")

    existing_admin = await admins_collection.find_one({"email": email})
    if existing_admin:
        raise HTTPException(status_code=400, detail="Admin already exists")

    custom_admin_id = generate_admin_id()

    new_admin_data = {
        "_id": custom_admin_id,
        "email": email,
        "name": name,
        "phone_no": phone_no,
        "organization_id": org_id,
        "organization": org_name,
        "created_at": datetime.now(timezone.utc),
        "created_by_admin_id": admin["admin_id"],
        "role": "admin",
        "is_verified": True
    }

    await admins_collection.insert_one(new_admin_data)

    await send_admin_invitation(email, name, org_name)

    return {
        "message": "Admin created successfully",
        "admin_id": custom_admin_id,
        "organization_id": org_id,
        "organization_name": org_name,
        "created_at": new_admin_data["created_at"]
    }

@router.get("/products/{organization_id}")
async def get_products_by_organization(
    organization_id: str,
    db: AsyncIOMotorDatabase = Depends(get_database),
    current_admin: dict = Depends(get_current_admin)
):
    products = await product_collection.find({"organization_id": organization_id}).to_list(None)

    if not products:
        raise HTTPException(status_code=404, detail="No products found for this organization")

    return {"organization_id": organization_id, "products": products}
    
@router.get("/get_orders", response_model=List[OrderResponse])
async def get_orders_by_admin(db: AsyncIOMotorDatabase = Depends(get_database), current_admin: dict = Depends(get_current_admin)):
    organization_id = current_admin["organization_id"]

    orders_cursor = orders_collection.find({"organization_id": organization_id})
    orders = await orders_cursor.to_list(length=100)

    if not orders:
        raise HTTPException(status_code=404, detail="No orders found for this organization")

    order_responses = []
    for order in orders:
        order_responses.append({
            "order_id": order["_id"],
            "employee_id": order["employee_id"],
            "clinic_hospital_name": order["clinic_hospital_name"],
            "clinic_hospital_address": order["clinic_hospital_address"],
            "items": order["items"],
            "total_amount": order["total_amount"],
            "payment_status": order["payment_status"],
            "delivered_status": order["delivered_status"],
            "order_date": order["order_date"]
        })

    return order_responses

@router.put("/orders/{order_id}/complete")
async def complete_order(order_id: str, admin: dict = Depends(get_current_admin)):
    organization_id = admin.get("organization_id")
    if not organization_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    order = await orders_collection.find_one({"_id": order_id})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    employee_id = order.get("employee_id")
    if not employee_id:
        raise HTTPException(status_code=404, detail="Employee ID not found in order")

    employee = await employee_collection.find_one({"_id": employee_id})
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    for item in order["items"]:
        product = await product_collection.find_one({
            "name": item["name"],
            "category": item["category"],
            "manufacturer": item["manufacturer"]
        })

        if not product:
            raise HTTPException(status_code=404, detail=f"Product {item['name']} not found")

        if product["quantity"] < item["quantity"]:
            raise HTTPException(status_code=400, detail=f"Insufficient stock for {item['name']}")

        await product_collection.update_one(
            {"_id": product["_id"]},
            {"$inc": {"quantity": -item["quantity"]}}
        )

    sale_id = generate_sale_id()
    await sales_collection.insert_one({
        "_id": sale_id,
        "order_id": order_id,
        "total_amount": order["total_amount"],
        "date": order["order_date"],
        "organization_id": organization_id,
        "employee": {
            "id": employee["_id"],
            "name": employee["name"],
            "email": employee["email"]
        }
    })

    await orders_collection.update_one(
        {"_id": order_id},
        {"$set": {
            "status": "Completed",
            "payment_status": "Completed",
            "delivered_status": "Completed"
        }}
    )

    return {"message": "Order completed successfully"}


@router.get("/sales")
async def get_all_sales(admin: dict = Depends(get_current_admin)):
    organization_id = admin.get("organization_id")

    if not organization_id:
        raise HTTPException(status_code=401, detail="Invalid token or missing organization ID")

    sales_cursor = sales_collection.find({"organization_id": organization_id})
    sales = []
    async for sale in sales_cursor:
        if "_id" not in sale or not isinstance(sale["_id"], str):
            sale["_id"] = generate_random_id("SALE")
            await sales_collection.update_one({"_id": sale["_id"]}, {"$set": {"_id": sale["_id"]}}, upsert=True)
        sales.append(sale)

    if not sales:
        raise HTTPException(status_code=404, detail="No sales found for this organization")

    return {"sales": sales}


@router.get("/sales/report")
async def get_sales_report(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    timeline: Optional[str] = "monthly",
    admin: dict = Depends(get_current_admin)
):
    organization_id = admin.get("organization_id")

    if not organization_id:
        raise HTTPException(status_code=401, detail="Invalid token or missing organization ID")

    date_filter = {}
    if start_date:
        date_filter["$gte"] = datetime.strptime(start_date, "%Y-%m-%d")
    if end_date:
        date_filter["$lte"] = datetime.strptime(end_date, "%Y-%m-%d")

    query = {"organization_id": organization_id}
    if date_filter:
        query["date"] = date_filter

    group_by = {
        "daily": {"$dateToString": {"format": "%Y-%m-%d", "date": "$date"}},
        "weekly": {"$isoWeekYear": "$date"},
        "monthly": {"$dateToString": {"format": "%Y-%m", "date": "$date"}},
    }

    if timeline not in group_by:
        raise HTTPException(status_code=400, detail="Invalid timeline value. Choose 'daily', 'weekly', or 'monthly'.")

    pipeline = [
        {"$match": query},
        {"$group": {
            "_id": group_by[timeline],
            "total_sales": {"$sum": "$total_amount"},
            "total_orders": {"$sum": 1},
        }},
        {"$sort": {"_id": 1}},
    ]

    sales_data = await sales_collection.aggregate(pipeline).to_list(length=None)

    if not sales_data:
        raise HTTPException(status_code=404, detail="No sales data found for the given parameters")

    return {"sales_report": sales_data}

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

    pipeline = [
        {"$match": query},
        {"$lookup": {
            "from": "employees",
            "localField": "employee_id",
            "foreignField": "_id",
            "as": "employee"
        }},
        {"$unwind": "$employee"}
    ]

    requests = await wfh_request.aggregate(pipeline).to_list(None)
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
        {"$set": {"status": status.value, "updated_at": datetime.utcnow()}}
    )

    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="WFH request not found or not updated")

    return {"message": f"WFH request {status.value.lower()} successfully"}


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
            "visit_id": str(visit["_id"]),
            "employee_id": str(visit["employee_id"]),
            "hospital_id": str(visit["hospital_id"]),
            "check_in_time": visit["check_in_time"],
            "check_out_time": visit.get("check_out_time"),
            "total_distance": total_distance,
            "locations": locations
        })

    return {"tracking_data": tracking_data}
