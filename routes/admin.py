from fastapi import APIRouter, HTTPException, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase

from database import get_database, employee_collection, admins_collection, sales_collection, visits_collection, product_collection
from security import get_current_admin
from datetime import datetime, timezone
from bson import ObjectId
from services.email_service import send_employee_invitation, send_admin_invitation
from models.products import OrderResponse





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
    """Admin creates an employee with email, name, and organization details"""

    # Ensure admin has an ObjectId
    try:
        admin_id = ObjectId(admin["admin_id"])  # Convert token's admin_id to ObjectId
        admin_data = await admins_collection.find_one({"_id": admin_id})
        
        if not admin_data:
            raise HTTPException(status_code=404, detail="Admin not found")
            
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid Admin ID format")

    # Fetch organization details from the organization collection
    org_id = admin_data.get("organization_id")
    if not org_id:
        raise HTTPException(status_code=400, detail="Organization ID missing for admin")

    organization_data = await db["organizations"].find_one({"_id": ObjectId(org_id)})
    if not organization_data:
        raise HTTPException(status_code=404, detail="Organization not found")

    org_name = organization_data.get("name")
    emp_limit = organization_data.get("emp_count", 0)

    # Check current employee count under this organization
    current_emp_count = await employee_collection.count_documents({"organization_id": org_id})

    # **Check if adding this employee will exceed the limit**
    if current_emp_count >= emp_limit:
        raise HTTPException(status_code=403, detail=f"Employee limit reached ({emp_limit}). Cannot add more employees.")

    # Check if the employee already exists
    existing_employee = await employee_collection.find_one({"email": email})
    if existing_employee:
        raise HTTPException(status_code=400, detail="Employee already exists")

    # Create new employee
    employee_data = {
        "email": email,
        "name": name,
        "organization_id": org_id,
        "organization": org_name,
        "created_at": datetime.now(timezone.utc),  
        "admin_id": admin_id,
        "role": "employee",
    }

    # Insert employee into the database
    new_employee = await employee_collection.insert_one(employee_data)

    # **✅ Auto-update total employees in the organization collection**
    await db["organizations"].update_one(
        {"_id": ObjectId(org_id)}, 
        {"$inc": {"total_employees": 1}}  # Increment employee count
    )

    await send_employee_invitation(email, name, org_name)

    return {
        "message": "Employee created successfully",
        "employee_id": str(new_employee.inserted_id),
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
    """
    Allows an admin to fetch an employee's location and provides a Google Maps URL.
    """
    organization_id = admin.get("organization_id")

    if not organization_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    # Fetch the employee's location
    employee = await employee_collection.find_one(
        {"_id": ObjectId(employee_id), "organization_id": organization_id},
        {"location": 1, "name": 1}
    )

    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found or does not belong to your organization")

    location = employee.get("location")
    if not location:
        raise HTTPException(status_code=404, detail="Location not available for this employee")

    latitude = location.get("latitude")
    longitude = location.get("longitude")

    # Generate Google Maps URL
    google_maps_url = f"https://www.google.com/maps?q={latitude},{longitude}"

    return {
        "employee_name": employee.get("name"),
        "location": {
            "latitude": latitude,
            "longitude": longitude,
            "updated_at": location.get("updated_at")
        },
        "google_maps_url": google_maps_url
    }

    
    
@router.get("/employees")    
async def get_all_employees(
    admin:dict = Depends(get_current_admin),
    db:AsyncIOMotorDatabase = Depends(get_database)
):
    
    admin_id = admin.get("admin_id")
    organization_id = admin.get("organization_id")
    
    
    if not admin_id:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    employees_cursor = employee_collection.find({"organization_id": ObjectId(organization_id)}, {"password":0})
    
    employees = []
    
    async for employee in employees_cursor:
        employees.append(convert_objectid_to_str(employee))
        
    return{
            "total_employees":len(employees),
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

    # Fetch total sales
    total_sales = await sales_collection.aggregate([
        {"$match": {"organization_id": org_id}},
        {"$group": {"_id": None, "totalSales": {"$sum": "$amount"}}}
    ]).to_list(length=1)

    # Fetch total visits
    total_visits = await visits_collection.count_documents({"organization_id": org_id})

    # Fetch total meetings
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

    # Fetch employee performance
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
                "name": "$name",
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

    # Fetch top 3 employees based on sales
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
                "name": "$name",
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

    # Fetch top 3 products based on sales
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
                "name": "$name",
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

    # Fetch yearly sales
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

    # Fetch monthly sales
    monthly_sales = await sales_collection.aggregate([
        {"$match": {"organization_id": org_id}},
        {
            "$group": {
                "_id": {"year": {"$year": "$date"}, "month": {"$month": "$date"}},
                "amount": {"$sum": "$amount"}
            }
        },
        {"$sort": {"_id.year": -1, "_id.month": -1}}
    ]).to_list(length=None)

    # Format yearly sales
    formatted_yearly_sales = [
        {"year": item["_id"]["year"], "amount": item["amount"]}
        for item in yearly_sales
    ]

    # Format monthly sales
    formatted_monthly_sales = [
        {"month": datetime(2025, item["_id"]["month"], 1).strftime("%b"), "year": item["_id"]["year"], "amount": item["amount"]}
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

    # Convert ObjectId to string for JSON response
    return [
        {
            "organization_id": str(org["_id"]),
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
    """Admin creates another admin within the same organization"""

    # Ensure admin has an ObjectId
    try:
        admin_id = ObjectId(admin["admin_id"])  # Convert token's admin_id to ObjectId
        admin_data = await admins_collection.find_one({"_id": admin_id})
        
        if not admin_data:
            raise HTTPException(status_code=404, detail="Admin not found")
            
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid Admin ID format")

    # Fetch organization details from the creating admin
    org_id = admin_data.get("organization_id")  # Ensure admin has organization_id
    org_name = admin_data.get("organization")
    
    if not org_id or not org_name:
        raise HTTPException(status_code=400, detail="Organization details missing for admin")

    # Check if the admin already exists
    existing_admin = await admins_collection.find_one({"email": email})
    if existing_admin:
        raise HTTPException(status_code=400, detail="Admin already exists")

    # Create new admin
    new_admin_data = {
        "email": email,
        "name": name,
        "phone_no": phone_no,
        "organization_id": org_id,
        "organization": org_name,
        "created_at": datetime.now(timezone.utc),  
        "created_by_admin_id": admin_id,
        "role": "admin",
        "is_verified": True 
    }

    # Insert admin into the database
    new_admin = await admins_collection.insert_one(new_admin_data)

    await send_admin_invitation(email, name, org_name)

    return {
        "message": "Admin created successfully",
        "admin_id": str(new_admin.inserted_id),
        "organization_id": org_id,
        "organization_name": org_name,
        "created_at": new_admin_data["created_at"]
    }


@router.get("/products/{organization_id}")
async def get_products_by_organization(
    organization_id: str,
    db: AsyncIOMotorDatabase = Depends(get_database),
    current_admin: dict = Depends(get_current_admin)  # Ensure only Admins can fetch products
):
    # Fetch products for the given organization
    products = await db.products_collection.find({"organization_id": organization_id}).to_list(None)

    if not products:
        raise HTTPException(status_code=404, detail="No products found for this organization")

    return {"organization_id": organization_id, "products": products} 

@router.get("/get_orders", response_model=List[OrderResponse])
async def get_orders_by_admin(db: AsyncIOMotorDatabase = Depends(get_database), current_admin: dict = Depends(get_current_admin)):
    # Extract organization_id from the current admin's details
    organization_id = current_admin["organization_id"]
    
    # Fetch orders associated with the organization_id from the database
    orders_cursor = db.orders_collection.find({"organization_id": organization_id})

    orders = await orders_cursor.to_list(length=100)

    if not orders:
        raise HTTPException(status_code=404, detail="No orders found for this organization")

    # Prepare the response
    order_responses = []
    for order in orders:
        order_responses.append({
            "order_id": str(order["_id"]),
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
    # Get admin details (not needed to fetch employee ID)
    organization_id = admin.get("organization_id")
    if not organization_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    # Fetch the order from the database
    order = await orders_collection.find_one({"_id": ObjectId(order_id)})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    # Convert order ObjectId fields to string
    order = convert_objectid_to_str(order)

    # Fetch the employee who placed the order
    employee_id = order.get("employee_id")
    if not employee_id:
        raise HTTPException(status_code=404, detail="Employee ID not found in order")

    employee = await employee_collection.find_one({"_id": ObjectId(employee_id)})
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    # Convert employee ObjectId fields to string
    employee = convert_objectid_to_str(employee)

    # Process the items in the order
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

        # Update product quantity
        await product_collection.update_one(
            {"_id": product["_id"]},
            {"$inc": {"quantity": -item["quantity"]}}
        )

    # Update sales record with employee and organization details
    await sales_collection.insert_one({
        "order_id": order_id,
        "total_amount": order["total_amount"],
        "date": order["order_date"],
        "organization_id": organization_id,  # Include organization_id from admin
        "employee": {
            "id": str(employee["_id"]),
            "name": employee["name"],
            "email": employee["email"]
        }
    })

    # Mark the order as completed and update its status
    await orders_collection.update_one(
        {"_id": ObjectId(order_id)},
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
    
    # Fetch all sales for the organization
    sales_cursor = sales_collection.find({"organization_id": organization_id})
    
    # Convert the ObjectId fields to strings
    sales = [convert_objectid_to_str(sale) async for sale in sales_cursor]
    
    if not sales:
        raise HTTPException(status_code=404, detail="No sales found for this organization")
    
    return {"sales": sales}

@router.get("/sales/report")
async def get_sales_report(
    start_date: Optional[str] = None,  # Optional start date for filtering
    end_date: Optional[str] = None,    # Optional end date for filtering
    timeline: Optional[str] = "monthly",  # Default timeline is 'monthly' (can be 'daily', 'weekly', or 'monthly')
    admin: dict = Depends(get_current_admin)
):
    organization_id = admin.get("organization_id")
    
    if not organization_id:
        raise HTTPException(status_code=401, detail="Invalid token or missing organization ID")
    
    # Convert string date inputs to datetime objects
    date_filter = {}
    if start_date:
        date_filter["$gte"] = datetime.strptime(start_date, "%Y-%m-%d")
    if end_date:
        date_filter["$lte"] = datetime.strptime(end_date, "%Y-%m-%d")
    
    # Query to find all sales for the organization within the date range if specified
    query = {"organization_id": organization_id}
    if date_filter:
        query["date"] = date_filter

    # Build the aggregation pipeline
    group_by = {
        "daily": {"$dateToString": {"format": "%Y-%m-%d", "date": "$date"}},
        "weekly": {"$isoWeekYear": "$date"},  # Group by ISO week of the year
        "monthly": {"$dateToString": {"format": "%Y-%m", "date": "$date"}},  # Group by month
    }
    
    if timeline not in group_by:
        raise HTTPException(status_code=400, detail="Invalid timeline value. Choose 'daily', 'weekly', or 'monthly'.")

    # Aggregation pipeline for sales report
    pipeline = [
        {"$match": query},  # Filter by organization and date range
        {"$group": {
            "_id": group_by[timeline],
            "total_sales": {"$sum": "$total_amount"},  # Total sales for the period
            "total_orders": {"$sum": 1},  # Count the number of orders
        }},
        {"$sort": {"_id": 1}},  # Sort by the period (e.g., date or week)
    ]
    
    # Execute the aggregation
    sales_data = await sales_collection.aggregate(pipeline).to_list(length=None)
    
    # If no sales data is found
    if not sales_data:
        raise HTTPException(status_code=404, detail="No sales data found for the given parameters")

    # Convert ObjectId to string (in case the result contains ObjectId)
    sales_data = convert_objectid_to_str(sales_data)

    return {"sales_report": sales_data}



@router.get("/employees/{employee_id}/report")
async def get_employee_report(
    employee_id: str,
    start_date: Optional[str] = None,  
    end_date: Optional[str] = None,
    admin: dict = Depends(get_current_admin)
):
    organization_id = admin.get("organization_id")
    
    if not organization_id:
        raise HTTPException(status_code=401, detail="Unauthorized or missing organization ID")

    # Convert string date inputs to datetime objects
    date_filter = {}
    if start_date:
        date_filter["$gte"] = datetime.strptime(start_date, "%Y-%m-%d")
    if end_date:
        date_filter["$lte"] = datetime.strptime(end_date, "%Y-%m-%d")
    
    # Fetch Employee Details
    employee = await employee_collection.find_one({"_id": ObjectId(employee_id), "organization_id": organization_id})
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    # Count Orders Taken by Employee
    order_query = {"employee.id": employee_id, "organization_id": organization_id}
    if date_filter:
        order_query["order_date"] = date_filter

    orders = await orders_collection.find(order_query).to_list(length=None)
    total_orders = len(orders)
    total_sales = sum(order["total_amount"] for order in orders) if orders else 0

    # Count Visits Made by Employee
    visit_query = {"employee_id": employee_id, "organization_id": organization_id}
    if date_filter:
        visit_query["visit_date"] = date_filter

    visits = await visits_collection.count_documents(visit_query)

    # Check Employee Active Status
    active_status = employee.get("is_active", False)

    # Fetch Attendance Record (Present/Absent, Working/WFH)
    attendance_query = {"employee_id": employee_id, "organization_id": organization_id}
    if date_filter:
        attendance_query["date"] = date_filter

    attendance_records = await attendance_collection.find(attendance_query).to_list(length=None)

    # Convert ObjectId fields to string
    employee_data = convert_objectid_to_str(employee)
    
    # Final Response
    return {
        "employee": {
            "id": employee_data["_id"],
            "name": employee_data["name"],
            "email": employee_data["email"],
            "phone": employee_data["phone"],
            "organization_id": employee_data["organization_id"],
            "is_active": active_status,
        },
        "orders_taken": total_orders,
        "sales_made": total_sales,
        "visits_made": visits,
        "attendance": [
            {
                "date": str(att["date"]),
                "status": att["status"],  # Present / Absent
                "working_mode": att["working_mode"],  # Office / WFH
            }
            for att in attendance_records
        ]
    }
