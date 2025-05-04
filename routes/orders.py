from fastapi import APIRouter
from routes.admin_orders import router as admin_orders_router
from routes.employee_orders import router as employee_orders_router

router = APIRouter()

router.include_router(admin_orders_router, prefix="/admin", tags=["Admin Orders"])
router.include_router(employee_orders_router, prefix="/employee", tags=["Employee Orders"])