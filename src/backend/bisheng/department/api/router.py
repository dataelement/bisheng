"""Department module router aggregation.

Part of F002-department-tree.
"""

from fastapi import APIRouter

from bisheng.department.api.endpoints.department import router as department_router
from bisheng.department.api.endpoints.department_member import router as member_router

router = APIRouter(prefix='/departments', tags=['Department'])
router.include_router(department_router)
router.include_router(member_router)
