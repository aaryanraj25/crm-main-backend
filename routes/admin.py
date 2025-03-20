from fastapi import APIRouter, HTTPException, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase

from database import get_database, employee_collection, admins_collection
from security import get_current_admin
from datetime import datetime, timezone
from bson import ObjectId




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


@router.post("/admin/create-employee")
async def create_employee(
    email: str, 
    name: str, 
    db: AsyncIOMotorDatabase = Depends(get_database), 
    admin: dict = Depends(get_current_admin)  # Ensure admin is passed
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

    return {
        "message": "Employee created successfully",
        "employee_id": str(new_employee.inserted_id),
        "organization_id": org_id,
        "organization_name": org_name,
        "created_at": employee_data["created_at"]
    }

    
    
@router.get("/admin/employees")    
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
    
    
    