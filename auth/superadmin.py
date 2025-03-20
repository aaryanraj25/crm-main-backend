import os
from fastapi import APIRouter, HTTPException
from dotenv import load_dotenv
from database import users_collection
from dependencies import verify_password, create_access_token

load_dotenv

router = APIRouter()
SUPERADMIN_EMAIL = os.getenv("SUPERADMIN_EMAIL", "admin@example.com")

@router.post("/login")
async def superadmin_login(email:str, password:str):
    superadmin = await users_collection.find_one({"email": SUPERADMIN_EMAIL})
    
    if not superadmin or not verify_password(password, superadmin["password"]):
        raise HTTPException(status_code =401, detail="Invalid credentials")  
    token = create_access_token({"sub":superadmin["email"], "role":"superadmin"}) 
    return{"access_token": token, "token_type": "bearer"} 
    
    

