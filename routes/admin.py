from fastapi import APIRouter, HTTPException, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase

from database import get_database, employee_collection, admins_collection, sales_collection, visits_collection, product_collection
from security import get_current_admin
from datetime import datetime, timezone
from bson import ObjectId
from services.email_service import send_employee_invitation




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

    # Fetch organization details
    org_id = admin_data.get("organization_id")  # Ensure admin has organization_id
    org_name = admin_data.get("organization")
    emp_limit = admin_data.get("emp_count", 0)

    if not org_id or not org_name:
        raise HTTPException(status_code=400, detail="Organization details missing for admin")

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
        "role": "employee"
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

    
    
@router.get("/employees")    
async def get_all_employees(
    admin:dict = Depends(get_current_admin),
    db:AsyncIOMotorDatabase = Depends(get_database)
):
    
    admin_id = admin.get("admin_id")
    
    if not admin_id:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    employees_cursor = employee_collection.find({"admin_id": ObjectId(admin_id)}, {"password":0})
    
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
    
    
    