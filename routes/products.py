from fastapi import APIRouter, Depends, HTTPException,UploadFile, File
from motor.motor_asyncio import AsyncIOMotorDatabase
from bson import ObjectId
from models.products import ProductModel
from database import  product_collection, get_database
from security import get_current_admin, get_current_user
import pandas as pd

import httpx  # type: ignore # To download files from URLs
from io import BytesIO

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

@router.post("/admin/products")
async def add_product(
    product: ProductModel,
    admin: dict = Depends(get_current_admin)
):
    admin_id = admin.get("admin_id")
    organization_id = admin.get("organization_id")
    
    if not admin_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    product_data = product.model_dump()
    product_data["admin_id"] = ObjectId(admin_id)
    product_data["organization_id"] = ObjectId(organization_id) 

    # Check if the product already exists (same name, category, manufacturer)
    existing_product = await product_collection.find_one({
        "name": product_data["name"],
        "category": product_data["category"],
        "manufacturer": product_data["manufacturer"],
        "admin_id": ObjectId(admin_id),
        "organization_id": ObjectId(organization_id)
        
    })

    if existing_product:
        # If exists, ADD the new quantity to the existing quantity
        new_quantity = existing_product["quantity"] + product_data["quantity"]
        await product_collection.update_one(
            {"_id": existing_product["_id"]},
            {"$set": {"quantity": new_quantity}}
        )
        return {
            "message": "Product quantity updated successfully",
            "product_id": str(existing_product["_id"]),
            "updated_quantity": new_quantity
        }
    else:
        # If not exists, insert new product
        inserted_product = await product_collection.insert_one(product_data)
        return {
            "message": "Product added successfully",
            "product_id": str(inserted_product.inserted_id),
            "added_quantity": product_data["quantity"]
        }

async def read_excel_from_url(url: str):
    """Fetch Excel file from URL and return a Pandas DataFrame."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            response.raise_for_status()  # Raise error for bad response
            return pd.read_excel(BytesIO(response.content))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error reading Excel from URL: {str(e)}")

@router.post("/admin/products/upload")
async def upload_products_excel(
    file: UploadFile = File(None),
    file_url: str = None,
    admin: dict = Depends(get_current_admin)
):
    admin_id = admin.get("admin_id")
    organization_id = admin.get("organization_id")
    if not admin_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    if not file and not file_url:
        raise HTTPException(status_code=400, detail="Either file upload or file URL is required.")

    # Read the Excel file from either uploaded file or URL
    if file:
        if not file.filename.endswith(".xlsx"):
            raise HTTPException(status_code=400, detail="Only Excel (.xlsx) files are supported")
        df = pd.read_excel(file.file)
    elif file_url:
        df = await read_excel_from_url(file_url)

    # Ensure required columns exist
    required_columns = {"name", "category", "quantity", "price", "manufacturer"}
    if not required_columns.issubset(df.columns):
        raise HTTPException(status_code=400, detail=f"Missing required columns: {required_columns - set(df.columns)}")

    updated_count = 0
    new_count = 0

    # Process each product in the Excel file
    for _, row in df.iterrows():
        product_name = row["name"].strip()
        product_category = row["category"].strip()
        product_quantity = int(row["quantity"])
        product_price = float(row["price"])
        manufacturer = row["manufacturer"].strip()

        # Check if product already exists for this admin
        existing_product = await product_collection.find_one({
            "name": product_name,
            "category": product_category,
            "manufacturer": manufacturer,
            "admin_id": ObjectId(admin_id)
        })

        if existing_product:
            # Update existing product's quantity
            await product_collection.update_one(
                {"_id": existing_product["_id"]},
                {"$inc": {"quantity": product_quantity}}
            )
            updated_count += 1
        else:
            # Insert new product
            product = {
                "name": product_name,
                "category": product_category,
                "quantity": product_quantity,
                "price": product_price,
                "manufacturer": manufacturer,
                "admin_id": ObjectId(admin_id),
                "organization_id": ObjectId(organization_id)
            }
            await product_collection.insert_one(product)
            new_count += 1

    return {
        "message": f"{updated_count} products updated, {new_count} new products added"
    }
    
@router.get("/products/{organization_id}")
async def get_products_by_organization(
    organization_id: str,
    db: AsyncIOMotorDatabase = Depends(get_database),
    current_user: dict = Depends(get_current_user)  # Allow any authenticated user
):
    # Validate if user belongs to the requested organization
    if current_user.get("organization_id") != organization_id:
        raise HTTPException(status_code=403, detail="Access denied")

    # Fetch products for the given organization
    products = await db.products_collection.find({"organization_id": organization_id}).to_list(None)

    if not products:
        raise HTTPException(status_code=404, detail="No products found for this organization")

    return {"organization_id": organization_id, "products": products}
    