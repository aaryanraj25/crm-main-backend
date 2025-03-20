import asyncio
from services.auth_service import initialize_super_admin

async def test_superadmin():
    await initialize_super_admin()

asyncio.run(test_superadmin())
