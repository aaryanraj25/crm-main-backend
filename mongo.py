from pymongo import MongoClient

MONGO_URI = "mongodb+srv://sharmasakshi96803:BixCf5ij8SAtLvvG@cluster0.lp8fo.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"

try:
    client = MongoClient(MONGO_URI)
    client.admin.command("ping")  # Sends a ping to check connection
    print("✅ Connected to MongoDB Atlas successfully!")
except Exception as e:
    print("❌ Failed to connect:", e)
