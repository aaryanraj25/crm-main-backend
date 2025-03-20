from motor.motor_asyncio import AsyncIOMotorClient
import os


MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://sharmasakshi96803:BixCf5ij8SAtLvvG@cluster0.lp8fo.mongodb.net/crm_db?retryWrites=true&w=majority&appName=Cluster0")
DATABASE_NAME = os.getenv("DATABASE_NAME", "crm_db")

client = AsyncIOMotorClient(MONGO_URI)
db = client[DATABASE_NAME]

users_collection = db["users"]
tasks_collection = db["tasks"]
logs_collection = db["logs"]
admins_collection = db["admin"]
employee_collection = db["employee"]
product_collection = db["products"]
attendance_collection = db["attendance"]
clinic_collection = db["clinic"]
visits_collection = db["visits"]
orders_collection = db["orders"]
sales_collection = db["sales"]
organization_collection = db["organization"]

def get_database():
    return db


async def connect_to_mongo():
    """Ensures MongoDB is connected."""
    try:
        await db.command('ping')
        print("Connected to MongoDB")
    except Exception as e:
        print(f"MongoDB Connection Error: {e}")
        




