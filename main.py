import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware  # Add this import
from database import connect_to_mongo
from services.auth_service import initialize_super_admin
from auth.superadmin import router as superadmin_router
from auth.admin import router as admin_router
from routes.superadmin import router as superadmin_Router
from routes.admin import router as admin_Router
from auth.employee import router as employee_router
from routes.employee import router as employee_Router
from routes.products import router as product_Router
from services.email_service import send_email

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await connect_to_mongo()
        await initialize_super_admin()
        logger.info("Application startup completed successfully.")
        yield
    except Exception as e:
        logger.error(f"Error during startup: {e}")
    finally:
        logger.info("Shutting down application...")

app = FastAPI(title="CRM Backend", version="1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://eplisio-admin-web-production.up.railway.app", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],  # Explicitly include OPTIONS
    allow_headers=["Content-Type", "Authorization"],  # Explicitly list needed headers
    max_age=86400,  # Cache preflight request results for 24 hours
)

# Include routers
app.include_router(superadmin_Router, prefix="/verification", tags=["SuperAdmin"])
app.include_router(admin_router, prefix="/admin", tags=["Admin"])
app.include_router(superadmin_router, prefix="/auth/superadmin", tags=["SuperAdmin"])
app.include_router(admin_Router, prefix="/admin", tags=["Admin"])
app.include_router(employee_router, prefix="/", tags=["employee"])
app.include_router(employee_Router, prefix="/", tags=["employee"])
app.include_router(product_Router, prefix="/product", tags=["Products"])

@app.get("/")
async def health_check():
    return {"status": "running"}

@app.middleware("http")
async def log_requests(request: Request, call_next):
    logger.info(f"Incoming request: {request.method} {request.url}")
    try:
        response = await call_next(request)
    except Exception as e:
        logger.error(f"Unhandled error: {e}", exc_info=True)
        raise e
    return response