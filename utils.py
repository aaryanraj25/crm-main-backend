# utils.py
import random
import string
from datetime import datetime, timezone

def generate_random_id(prefix="", length=6):
    """Generate a random ID with optional prefix"""
    random_str = ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))
    return f"{prefix}-{random_str}" if prefix else random_str

def generate_admin_id():
    return generate_random_id("ADMIN")

def generate_organization_id():
    return generate_random_id("ORG")

def generate_employee_id():
    return generate_random_id("EMP")

def generate_sale_id():
    return generate_random_id("SALE")

def generate_product_id():
    return generate_random_id("PROD")

def generate_visit_id():
    return generate_random_id("VISIT")

def generate_order_id():
    return generate_random_id("ORDER")

def get_current_datetime():
    """Get current datetime in UTC"""
    return datetime.now(timezone.utc)