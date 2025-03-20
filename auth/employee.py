from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import EmailStr
from database import get_database, employee_collection
from dependencies import hash_password, create_access_token, verify_password

router = APIRouter()

@router.post("/Set-employee-password")
async def set_employee_password(
    email: EmailStr,
    password:str,
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    employee = await employee_collection.find_one({"email": email})
    
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
        
    hashed_password = hash_password(password)    
    await employee_collection.update_one(
        {"email": email},
        {"$set":{"password": hashed_password}}
    )
    
    return {"message": "Password has been set successfully. You can now log in."}

@router.post("/employee-login")
async def employee_login(
    email: EmailStr,
    password: str,
    db:AsyncIOMotorDatabase = Depends(get_database)
):
    
    employee = await employee_collection.find_one({"email":email})
    
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    
    if not verify_password(password, employee.get("password")):
        raise HTTPException(status_code=401, detail="Invalid password")
    
    token = create_access_token({
    "employee_id": str(employee["_id"]),
    "role": "employee",
    "organization": str(employee.get("organization", "")),  # ✅ Organization Name (if available)
    "organization_id": str(employee.get("organization_id", "")),  # ✅ Organization ID
    "admin_id": str(employee.get("admin_id", ""))
})
    
    return {"message": "Login successful", "token": token}