# main.py
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from database import connect_to_mongo
from services.auth_service import initialize_super_admin
from auth.superadmin import router as superadmin_router
from auth.admin import router as admin_router
from routes.superadmin import router as superadmin_Router
from routes.admin import router as admin_Router
from auth.employee import router as employee_router
from routes.employee import router as employee_Router
from routes.products import router as product_Router
from routes.hospitals import router as hospital_router
from routes.orders import router as order_router
from routes.meetings import router as meetings_router
from routes.clients import router as clients_router

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
    allow_origins=["https://your-frontend-domain.com", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Router includes
app.include_router(superadmin_Router, prefix="/verification", tags=["SuperAdmin"])
app.include_router(admin_router, prefix="/admin", tags=["Admin"])
app.include_router(superadmin_router, prefix="/auth/superadmin", tags=["SuperAdmin"])
app.include_router(admin_Router, prefix="/admin", tags=["Admin"])
app.include_router(employee_router, prefix="/employee", tags=["Employee"])
app.include_router(employee_Router, prefix="/employee", tags=["Employee"])
app.include_router(product_Router, prefix="/product", tags=["Products"])
app.include_router(hospital_router, prefix="/hospital", tags=["Hospital"])
app.include_router(order_router, prefix="/orders", tags=["Orders"])
app.include_router(clients_router, prefix="/clients", tags=["Clients"])
app.include_router(meetings_router, prefix="/meetings", tags=["Meetings"])

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