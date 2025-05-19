import random
import string
from fastapi import APIRouter, HTTPException, Depends, Query
from motor.motor_asyncio import AsyncIOMotorDatabase
from typing import List, Optional
from datetime import datetime, timedelta, timezone
from database import (
    get_database, employee_collection, admins_collection,
    sales_collection, visits_collection, product_collection,
    organization_collection, orders_collection, attendance_collection,
    wfh_request, clinic_collection
)
from dependencies import hash_password
from security import get_current_admin
from services.email_service import send_admin_otp_email, send_employee_invitation, send_admin_invitation
from models.products import OrderResponse
from models.employee import WFHRequestStatus
from utils import (
    generate_employee_id, generate_admin_id,
    generate_sale_id, get_current_datetime
)
from geopy.distance import geodesic
from passlib.context import CryptContext
from math import radians, sin, cos, sqrt, atan2


router = APIRouter()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

# routes/admin.py
@router.post("/create-employee")
async def create_employee(
    email: str,
    name: str,
    db: AsyncIOMotorDatabase = Depends(get_database),
    current_admin: dict = Depends(get_current_admin)
):
    try:
        # Get admin details from token
        admin_id = current_admin["admin_id"]
        organization_id = current_admin["organization_id"]
        organization = current_admin["organization_name"]

        # Check if employee exists
        existing_employee = await employee_collection.find_one({"email": email})
        if existing_employee:
            raise HTTPException(status_code=400, detail="Employee already exists")

        # Create employee
        employee_id = generate_employee_id()
        employee_data = {
            "_id": employee_id,
            "email": email,
            "name": name,
            "organization_id": organization_id,
            "organization": organization,
            "admin_id": admin_id,
            "created_at": get_current_datetime(),
            "role": "employee"
        }

        await employee_collection.insert_one(employee_data)

        # Send invitation email
        try:
            await send_employee_invitation(email, name, organization)
        except Exception as e:
            print(f"Email error: {e}")

        return {
            "message": "Employee created successfully",
            "employee_id": employee_id
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/admin/profile")
async def get_admin_profile(
    db: AsyncIOMotorDatabase = Depends(get_database),
    current_admin: dict = Depends(get_current_admin)
):
    try:
        admin_id = current_admin["admin_id"]

        # Get detailed admin information from database
        admin_profile = await admins_collection.find_one({"_id": admin_id})

        if not admin_profile:
            raise HTTPException(status_code=404, detail="Admin profile not found")

        # Get organization details
        organization = await organization_collection.find_one(
            {"_id": admin_profile["organization_id"]}
        )

        # Get counts of employees, total sales, and total orders
        employee_count = await employee_collection.count_documents(
            {"organization_id": admin_profile["organization_id"]}
        )

        total_sales = await sales_collection.aggregate([
            {"$match": {"organization_id": admin_profile["organization_id"]}},
            {"$group": {"_id": None, "total": {"$sum": "$total_amount"}}}
        ]).to_list(length=1)

        total_orders = await orders_collection.count_documents(
            {"organization_id": admin_profile["organization_id"]}
        )

        # Construct response
        profile_data = {
            "admin_id": admin_profile["_id"],
            "name": admin_profile["name"],
            "email": admin_profile["email"],
            "phone": admin_profile.get("phone", ""),
            "role": admin_profile["role"],
            "created_at": admin_profile["created_at"],
            "organization": {
                "id": admin_profile["organization_id"],
                "name": admin_profile["organization"],
                "details": organization if organization else None
            },
            "statistics": {
                "total_employees": employee_count,
                "total_sales": total_sales[0]["total"] if total_sales else 0,
                "total_orders": total_orders
            },
            "permissions": admin_profile.get("permissions", []),
            "last_login": admin_profile.get("last_login"),
            "is_verified": admin_profile.get("is_verified", False)
        }

        return profile_data

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/admin/profile")
async def update_admin_profile(
    name: Optional[str] = None,
    phone: Optional[str] = None,
    current_admin: dict = Depends(get_current_admin)
):
    try:
        admin_id = current_admin["admin_id"]

        # Prepare update data
        update_data = {}
        if name:
            update_data["name"] = name
        if phone:
            update_data["phone"] = phone

        if not update_data:
            raise HTTPException(
                status_code=400,
                detail="No update data provided"
            )

        # Add updated_at timestamp
        update_data["updated_at"] = get_current_datetime()

        # Update admin profile
        result = await admins_collection.update_one(
            {"_id": admin_id},
            {"$set": update_data}
        )

        if result.modified_count == 0:
            raise HTTPException(
                status_code=404,
                detail="Admin profile not found or no changes made"
            )

        # Get updated profile
        updated_profile = await admins_collection.find_one({"_id": admin_id})

        return {
            "message": "Profile updated successfully",
            "admin_id": admin_id,
            "name": updated_profile["name"],
            "phone": updated_profile.get("phone", ""),
            "updated_at": updated_profile.get("updated_at")
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/admin/profile/change-password")
async def change_admin_password(
    current_password: str,
    new_password: str,
    db: AsyncIOMotorDatabase = Depends(get_database),
    current_admin: dict = Depends(get_current_admin)
):
    try:
        admin_id = current_admin["admin_id"]

        # Get admin from database
        admin = await admins_collection.find_one({"_id": admin_id})
        if not admin:
            raise HTTPException(status_code=404, detail="Admin not found")

        # Verify current password
        if not verify_password(current_password, admin["password"]):
            raise HTTPException(
                status_code=400,
                detail="Current password is incorrect"
            )

        # Hash new password
        hashed_password = get_password_hash(new_password)

        # Update password
        result = await admins_collection.update_one(
            {"_id": admin_id},
            {
                "$set": {
                    "password": hashed_password,
                    "password_updated_at": get_current_datetime()
                }
            }
        )

        if result.modified_count == 0:
            raise HTTPException(
                status_code=500,
                detail="Failed to update password"
            )

        return {"message": "Password updated successfully"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/employee-location/{employee_id}")
async def get_employee_location(
    employee_id: str,
    admin: dict = Depends(get_current_admin)
):
    organization_id = admin.get("organization_id")
    if not organization_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    employee = await employee_collection.find_one(
        {"_id": employee_id, "organization_id": organization_id},
        {"location": 1, "name": 1}
    )

    if not employee:
        raise HTTPException(
            status_code=404,
            detail="Employee not found or does not belong to your organization"
        )

    location = employee.get("location")
    if not location:
        raise HTTPException(status_code=404, detail="Location not available")

    return {
        "employee_name": employee.get("name"),
        "location": {
            "latitude": location.get("latitude"),
            "longitude": location.get("longitude"),
            "updated_at": location.get("updated_at")
        },
        "google_maps_url": f"https://www.google.com/maps?q={location.get('latitude')},{location.get('longitude')}"
    }

@router.get("/organization-stats")
async def get_organization_stats(
    db: AsyncIOMotorDatabase = Depends(get_database),
    admin: dict = Depends(get_current_admin)
):
    org_id = admin.get("organization_id")
    if not org_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    total_sales = await sales_collection.aggregate([
        {"$match": {"organization_id": org_id}},
        {"$group": {"_id": None, "totalSales": {"$sum": "$total_amount"}}}  # Changed from $amount to $total_amount
    ]).to_list(length=1)

    total_visits = await clinic_collection.count_documents({"organization_id": org_id})
    total_meetings = await visits_collection.count_documents({
        "organization_id": org_id,
        "type": "meeting"
    })

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
    org_id = admin.get("organization_id")
    if not org_id:
        raise HTTPException(status_code=401, detail="Invalid token")

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
    org_id = admin.get("organization_id")
    if not org_id:
        raise HTTPException(status_code=401, detail="Invalid token")

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
                "salesAmount": {"$sum": "$sales_data.total_amount"}  # Changed from amount to total_amount
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
    org_id = admin.get("organization_id")
    if not org_id:
        raise HTTPException(status_code=401, detail="Invalid token")

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
    org_id = admin.get("organization_id")
    if not org_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    # Add a $addFields stage to handle both date fields
    date_handling = {
        "$addFields": {
            "sale_date": {
                "$cond": {
                    "if": {"$ne": ["$date", None]},
                    "then": "$date",
                    "else": "$created_at"
                }
            }
        }
    }

    # Daily sales (past 30 days)
    daily_sales = await sales_collection.aggregate([
        {"$match": {"organization_id": org_id}},
        date_handling,
        {
            "$group": {
                "_id": {
                    "year": {"$year": "$sale_date"},
                    "month": {"$month": "$sale_date"},
                    "day": {"$dayOfMonth": "$sale_date"}
                },
                "amount": {"$sum": "$total_amount"}
            }
        },
        {"$sort": {"_id.year": -1, "_id.month": -1, "_id.day": -1}},
        {"$limit": 30}
    ]).to_list(length=None)

    # Weekly sales (past 12 weeks)
    weekly_sales = await sales_collection.aggregate([
        {"$match": {"organization_id": org_id}},
        date_handling,
        {
            "$group": {
                "_id": {
                    "year": {"$year": "$sale_date"},
                    "week": {"$week": "$sale_date"}
                },
                "amount": {"$sum": "$total_amount"}
            }
        },
        {"$sort": {"_id.year": -1, "_id.week": -1}},
        {"$limit": 12}
    ]).to_list(length=None)

    # Monthly sales (past 12 months)
    monthly_sales = await sales_collection.aggregate([
        {"$match": {"organization_id": org_id}},
        date_handling,
        {
            "$group": {
                "_id": {
                    "year": {"$year": "$sale_date"},
                    "month": {"$month": "$sale_date"}
                },
                "amount": {"$sum": "$total_amount"}
            }
        },
        {"$sort": {"_id.year": -1, "_id.month": -1}},
        {"$limit": 12}
    ]).to_list(length=None)

    # Yearly sales
    yearly_sales = await sales_collection.aggregate([
        {"$match": {"organization_id": org_id}},
        date_handling,
        {
            "$group": {
                "_id": {"year": {"$year": "$sale_date"}},
                "amount": {"$sum": "$total_amount"}
            }
        },
        {"$sort": {"_id.year": -1}}
    ]).to_list(length=None)

    # Safe formatting of dates with null checks
    formatted_daily_sales = []
    for item in daily_sales:
        try:
            if all(item['_id'].get(k) is not None for k in ['year', 'month', 'day']):
                formatted_daily_sales.append({
                    "date": f"{item['_id']['year']}-{item['_id']['month']:02d}-{item['_id']['day']:02d}",
                    "amount": item["amount"]
                })
        except (KeyError, TypeError):
            continue

    formatted_weekly_sales = []
    for item in weekly_sales:
        try:
            if all(item['_id'].get(k) is not None for k in ['year', 'week']):
                formatted_weekly_sales.append({
                    "year": item["_id"]["year"],
                    "week": item["_id"]["week"],
                    "amount": item["amount"]
                })
        except (KeyError, TypeError):
            continue

    formatted_monthly_sales = []
    for item in monthly_sales:
        try:
            if all(item['_id'].get(k) is not None for k in ['year', 'month']):
                formatted_monthly_sales.append({
                    "month": datetime(item["_id"]["year"], item["_id"]["month"], 1).strftime("%b"),
                    "year": item["_id"]["year"],
                    "amount": item["amount"]
                })
        except (KeyError, TypeError, ValueError):
            continue

    formatted_yearly_sales = []
    for item in yearly_sales:
        try:
            if item['_id'].get('year') is not None:
                formatted_yearly_sales.append({
                    "year": item["_id"]["year"],
                    "amount": item["amount"]
                })
        except (KeyError, TypeError):
            continue

    return {
        "dailySales": formatted_daily_sales,
        "weeklySales": formatted_weekly_sales,
        "monthlySales": formatted_monthly_sales,
        "yearlySales": formatted_yearly_sales
    }


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

    requests = await wfh_request.aggregate([
        {"$match": query},
        {
            "$lookup": {
                "from": "employees",
                "localField": "employee_id",
                "foreignField": "_id",
                "as": "employee"
            }
        },
        {"$unwind": "$employee"}
    ]).to_list(None)

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
        {
            "$set": {
                "status": status.value,
                "updated_at": get_current_datetime(),
                "updated_by": admin["admin_id"]
            }
        }
    )

    if result.modified_count == 0:
        raise HTTPException(
            status_code=404,
            detail="WFH request not found or not updated"
        )

    return {"message": f"WFH request {status.value} successfully"}

@router.post("/admin/create-admin")
async def create_admin(
    email: str,
    name: str,
    phone: str,
    db: AsyncIOMotorDatabase = Depends(get_database),
    admin: dict = Depends(get_current_admin)
):
    admin_data = await admins_collection.find_one({"_id": admin["admin_id"]})
    if not admin_data:
        raise HTTPException(status_code=404, detail="Admin not found")

    org_id = admin_data.get("organization_id")
    org_name = admin_data.get("organization")

    if not org_id or not org_name:
        raise HTTPException(
            status_code=400,
            detail="Organization details missing for admin"
        )

    existing_admin = await admins_collection.find_one({"email": email})
    if existing_admin:
        raise HTTPException(status_code=400, detail="Admin already exists")

    new_admin_id = generate_admin_id()

    new_admin_data = {
        "_id": new_admin_id,
        "email": email,
        "name": name,
        "phone": phone,
        "organization_id": org_id,
        "organization": org_name,
        "created_at": get_current_datetime(),
        "created_by_admin_id": admin["admin_id"],
        "role": "admin",
        "is_verified": True
    }

    await admins_collection.insert_one(new_admin_data)
    await send_admin_invitation(email, name, org_name)

    return {
        "message": "Admin created successfully",
        "admin_id": new_admin_id,
        "organization_id": org_id,
        "organization_name": org_name,
        "created_at": new_admin_data["created_at"]
    }



def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate distance between two points using Haversine formula
    Returns distance in kilometers
    """
    try:
        R = 6371  # Earth's radius in kilometers

        # Convert coordinates to radians
        lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])

        # Haversine formula
        dlat = lat2 - lat1
        dlon = lon2 - lon1

        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
        c = 2 * atan2(sqrt(a), sqrt(1-a))
        distance = R * c

        return round(distance, 2)
    except Exception as e:
        print(f"Error calculating distance: {e}")
        return 0

@router.get("/employee-tracking")
async def get_employee_tracking(
    date: Optional[str] = None,
    employee_id: Optional[str] = None,
    admin: dict = Depends(get_current_admin),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """Get employee tracking data with distance calculation"""
    try:
        organization_id = admin.get("organization_id")
        if not organization_id:
            raise HTTPException(status_code=401, detail="Invalid token")

        # Build base query for attendance
        query_date = None
        if date:
            try:
                query_date = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid date format. Use YYYY-MM-DD"
                )
        else:
            query_date = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

        # Add employee filter
        attendance_query = {
            "organization_id": organization_id,
            "date": query_date
        }
        if employee_id:
            attendance_query["employee_id"] = employee_id

        # Get attendance records for the day
        attendance_collection = db["attendance"]
        employee_collection = db["employee"]
        visits_collection = db["visits"]

        attendance_records = await attendance_collection.find(attendance_query).to_list(None)

        tracking_data = []
        for attendance in attendance_records:
            emp_id = attendance["employee_id"]

            # Get employee details
            employee = await employee_collection.find_one({"_id": emp_id})
            if not employee:
                continue

            # Initialize tracking info
            employee_tracking = {
                "employee_id": emp_id,
                "employee_name": employee.get("name", "Unknown"),
                "date": attendance["date"],
                "clock_in_time": attendance.get("clock_in_time"),
                "clock_out_time": attendance.get("clock_out_time"),
                "work_from_home": attendance.get("work_from_home", False),
                "route_points": [],
                "route_segments": [],
                "total_distance": 0,
                "status": "checked_out" if attendance.get("clock_out_time") else "checked_in"
            }

            if not attendance.get("work_from_home"):
                # Get all location points for the day
                all_points = []

                # Add clock-in location if exists
                if clock_in_loc := attendance.get("clock_in_location"):
                    all_points.append({
                        "type": "clock_in",
                        "latitude": clock_in_loc["latitude"],
                        "longitude": clock_in_loc["longitude"],
                        "timestamp": attendance["clock_in_time"]
                    })

                # Get all visits for the day
                visits_query = {
                    "employee_id": emp_id,
                    "organization_id": organization_id,
                    "check_in_time": {
                        "$gte": query_date,
                        "$lt": query_date + timedelta(days=1)
                    }
                }

                visits = await visits_collection.find(visits_query).sort("check_in_time", 1).to_list(None)

                # Add all visit locations
                for visit in visits:
                    if locations := visit.get("locations", []):
                        for loc in locations:
                            all_points.append({
                                "type": "visit",
                                "visit_id": visit["_id"],
                                "clinic_name": visit.get("clinic_name", "Unknown"),
                                "latitude": loc["latitude"],
                                "longitude": loc["longitude"],
                                "timestamp": loc["timestamp"]
                            })

                # Add clock-out location if exists
                if clock_out_loc := attendance.get("clock_out_location"):
                    all_points.append({
                        "type": "clock_out",
                        "latitude": clock_out_loc["latitude"],
                        "longitude": clock_out_loc["longitude"],
                        "timestamp": attendance["clock_out_time"]
                    })

                # Sort all points by timestamp
                all_points.sort(key=lambda x: x["timestamp"])
                employee_tracking["route_points"] = all_points

                # Calculate distances between consecutive points
                total_distance = 0
                route_segments = []

                for i in range(len(all_points) - 1):
                    point1 = all_points[i]
                    point2 = all_points[i + 1]

                    # Calculate distance between points
                    distance = calculate_distance(
                        point1["latitude"],
                        point1["longitude"],
                        point2["latitude"],
                        point2["longitude"]
                    )

                    # Create segment info
                    segment = {
                        "from": {
                            "type": point1["type"],
                            "latitude": point1["latitude"],
                            "longitude": point1["longitude"],
                            "timestamp": point1["timestamp"],
                            "clinic_name": point1.get("clinic_name")
                        },
                        "to": {
                            "type": point2["type"],
                            "latitude": point2["latitude"],
                            "longitude": point2["longitude"],
                            "timestamp": point2["timestamp"],
                            "clinic_name": point2.get("clinic_name")
                        },
                        "distance": distance,
                        "duration": str(point2["timestamp"] - point1["timestamp"])
                    }
                    route_segments.append(segment)
                    total_distance += distance

                employee_tracking["route_segments"] = route_segments
                employee_tracking["total_distance"] = round(total_distance, 2)

            tracking_data.append(employee_tracking)

        # Prepare summary
        summary = {
            "date": date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "total_employees": len(tracking_data),
            "total_distance_covered": round(sum(t["total_distance"] for t in tracking_data), 2),
            "checked_in": len([t for t in tracking_data if t["status"] == "checked_in"]),
            "checked_out": len([t for t in tracking_data if t["status"] == "checked_out"]),
            "work_from_home": len([t for t in tracking_data if t["work_from_home"]])
        }

        return {
            "summary": summary,
            "tracking_data": tracking_data
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving tracking data: {str(e)}"
        )

@router.get("/employee-tracking/{employee_id}/daily-summary")
async def get_employee_daily_summary(
    employee_id: str,
    start_date: str,
    end_date: Optional[str] = None,
    admin: dict = Depends(get_current_admin),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """Get daily summary of employee tracking data"""
    try:
        organization_id = admin.get("organization_id")
        if not organization_id:
            raise HTTPException(status_code=401, detail="Invalid token")

        # Validate employee
        employee_collection = db["employee"]
        employee = await employee_collection.find_one({
            "_id": employee_id,
            "organization_id": organization_id
        })
        if not employee:
            raise HTTPException(status_code=404, detail="Employee not found")

        # Parse dates
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            end = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc) if end_date else start + timedelta(days=1)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

        # Get attendance records
        attendance_collection = db["attendance"]
        attendance_records = await attendance_collection.find({
            "employee_id": employee_id,
            "organization_id": organization_id,
            "date": {
                "$gte": start,
                "$lt": end + timedelta(days=1)
            }
        }).sort("date", 1).to_list(None)

        daily_summaries = []
        for attendance in attendance_records:
            daily_data = {
                "date": attendance["date"],
                "clock_in_time": attendance.get("clock_in_time"),
                "clock_out_time": attendance.get("clock_out_time"),
                "work_from_home": attendance.get("work_from_home", False),
                "total_distance": 0,
                "total_visits": 0,
                "work_duration": None
            }

            if not attendance.get("work_from_home"):
                # Calculate distance if locations exist
                if clock_in_loc := attendance.get("clock_in_location"):
                    if clock_out_loc := attendance.get("clock_out_location"):
                        distance = calculate_distance(
                            clock_in_loc["latitude"],
                            clock_in_loc["longitude"],
                            clock_out_loc["latitude"],
                            clock_out_loc["longitude"]
                        )
                        daily_data["total_distance"] = distance

            # Calculate work duration if both clock times exist
            if attendance.get("clock_in_time") and attendance.get("clock_out_time"):
                duration = attendance["clock_out_time"] - attendance["clock_in_time"]
                daily_data["work_duration"] = str(duration)

            # Get visits count for the day
            visits_collection = db["visits"]
            visits_count = await visits_collection.count_documents({
                "employee_id": employee_id,
                "organization_id": organization_id,
                "check_in_time": {
                    "$gte": attendance["date"],
                    "$lt": attendance["date"] + timedelta(days=1)
                }
            })
            daily_data["total_visits"] = visits_count

            daily_summaries.append(daily_data)

        return {
            "employee_id": employee_id,
            "employee_name": employee.get("name", "Unknown"),
            "start_date": start_date,
            "end_date": end_date or start_date,
            "daily_summaries": daily_summaries,
            "summary": {
                "total_days": len(daily_summaries),
                "total_distance": round(sum(d["total_distance"] for d in daily_summaries), 2),
                "total_visits": sum(d["total_visits"] for d in daily_summaries),
                "wfh_days": len([d for d in daily_summaries if d["work_from_home"]])
            }
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving daily summary: {str(e)}"
        )

@router.get("/admin/employees")
async def get_employees_by_admin(
    admin: dict = Depends(get_current_admin),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    organization_id = admin.get("organization_id")
    if not organization_id:
        raise HTTPException(status_code=400, detail="Admin does not belong to an organization")

    employee_collection = db["employee"]
    employees_cursor = employee_collection.find({"organization_id": organization_id})
    employees = await employees_cursor.to_list(length=None)

    if not employees:
        raise HTTPException(status_code=404, detail="No employees found for your organization")

    return {"organization_id": organization_id, "employees": employees}


@router.get("/admin/employee/{employee_id}")
async def get_employee_details(
    employee_id: str,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    order_status: Optional[str] = Query(None, description="Filter by delivered_status: Pending, Rejected, Completed"),
    attendance_status: Optional[str] = Query(None, description="Filter attendance by status: Active, Inactive"),
    admin: dict = Depends(get_current_admin),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    employee_collection = db["employee"]
    orders_collection = db["orders"]
    sales_collection = db["sales"]
    attendance_collection = db["attendance"]
    client_collection = db["client"]
    clinic_collection = db["clinic"]

    # Admin's organization ID
    org_id = admin.get("organization_id")
    if not org_id:
        raise HTTPException(status_code=403, detail="Invalid admin organization")

    # Get employee
    employee = await employee_collection.find_one({"_id": employee_id, "organization_id": org_id})
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found in your organization")

    # Parse date filters or use current month if not provided
    now = datetime.now()
    if start_date and end_date:
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d")
            end = datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")
    else:
        # Default to current month
        start = datetime(now.year, now.month, 1)
        end = now  # Current date
    
    date_filter = {"$gte": start, "$lte": end}
    
    # Calculate total days in the date range (including today)
    total_days = (end.date() - start.date()).days + 1
    # Limit to current day (we don't count future days in the current month)
    effective_days = min(total_days, (now.date() - start.date()).days + 1)

    # Orders filter
    order_query = {"employee_id": employee_id, "status": "completed"}
    if order_status:
        order_query["delivered_status"] = order_status
    orders = await orders_collection.find(order_query).to_list(length=None)

    # Fetch clinics if orders contain clinic_id
    clinic_ids = list({order.get("clinic_id") for order in orders if order.get("clinic_id")})
    clinics = await clinic_collection.find({"_id": {"$in": clinic_ids}}).to_list(length=None)
    clinic_map = {clinic["_id"]: clinic for clinic in clinics}

    # Enrich orders with clinic name and address
    for order in orders:
        clinic_id = order.get("clinic_id")
        clinic_info = clinic_map.get(clinic_id)
        if clinic_info:
            order["clinic_hospital_name"] = clinic_info.get("name")
            order["clinic_hospital_address"] = clinic_info.get("address")
        else:
            order["clinic_hospital_name"] = None
            order["clinic_hospital_address"] = None

    # Sales filter
    sales_query = {"employee_id": employee_id}
    sales_query["date"] = date_filter
    sales = await sales_collection.find(sales_query).to_list(length=None)

    # Attendance filter with date range
    attendance_query = {"employee_id": employee_id, "date": date_filter}
    if attendance_status:
        attendance_query["status"] = attendance_status
    
    # Count days with active attendance
    attendance_records = await attendance_collection.find(attendance_query).to_list(length=None)
    
    # Count days marked as "Active" (or whatever status indicates attendance)
    active_days = sum(1 for record in attendance_records if record.get("status") == "Active")
    
    # Format attendance as "days attended / total days"
    attendance_summary = {
    "attended_days": len(attendance_records),
    "total_days": effective_days,
    "ratio": f"{len(attendance_records)}/{effective_days}",
    "percentage": round((len(attendance_records) / effective_days) * 100, 2) if effective_days > 0 else 0,
    "records": attendance_records  # Include detailed records for reference
    }

    # Clients
    client = await client_collection.find({"employee_id": employee_id}).to_list(length=None)

    return {
        "employee": employee,
        "orders": orders,
        "sales": sales,
        "attendance": attendance_summary,
        "clients": client
    }

@router.post("/admin/forgot-password/request")
async def request_otp(email: str, db: AsyncIOMotorDatabase = Depends(get_database)):
    admin = await db["admin"].find_one({"email": email})
    if not admin:
        raise HTTPException(status_code=404, detail="Admin not found")

    otp = generate_otp()
    otp_store[email] = {
        "otp": otp,
        "expires": datetime.utcnow() + timedelta(minutes=10)
    }

    await send_admin_otp_email(email,admin["name"], otp)
    return {"message": "OTP sent to email"}

@router.post("/admin/forgot-password/verify")
async def verify_otp(email: str, otp: str):
    otp_data = otp_store.get(email)
    if not otp_data:
        raise HTTPException(status_code=400, detail="No OTP found")

    if otp_data["expires"] < datetime.utcnow():
        otp_store.pop(email, None)
        raise HTTPException(status_code=400, detail="OTP expired")

    if otp_data["otp"] != otp:
        raise HTTPException(status_code=400, detail="Invalid OTP")

    return {"message": "OTP verified"}

@router.post("/admin/forgot-password/reset")
async def reset_password(email: str, new_password: str, db: AsyncIOMotorDatabase = Depends(get_database)):
    if email not in otp_store:
        raise HTTPException(status_code=400, detail="OTP not verified")

    hashed = hash_password(new_password)
    await db["admin"].update_one({"email": email}, {"$set": {"password": hashed}})
    otp_store.pop(email, None)

    return {"message": "Password updated successfully"}