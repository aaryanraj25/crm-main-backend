from passlib.context import CryptContext
from database import users_collection
import os
from dotenv import load_dotenv

load_dotenv()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

SUPERADMIN_EMAIL = os.getenv("SUPERADMIN_EMAIL")
SUPERADMIN_PASSWORD = os.getenv("SUPERADMIN_PASSWORD")

async def initialize_super_admin():
    existing_superadmin = await users_collection.find_one({"role": "superadmin"})

    if not existing_superadmin:
        hashed_password = pwd_context.hash(SUPERADMIN_PASSWORD)
        await users_collection.insert_one({
            "email": SUPERADMIN_EMAIL,
            "password": hashed_password,
            "role": "superadmin"
        })
        print("Super Admin created successfully!")