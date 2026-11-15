"""Department module router aggregation.

Part of F002-department-tree.
"""

from fastapi import APIRouter

from bisheng.department.api.endpoints.department import router as department_router
from bisheng.department.api.endpoints.department_member import router as member_router
from bisheng.department.api.endpoints.organization_search import router as organization_search_router

router = APIRouter(prefix="/departments", tags=["Department"])
router.include_router(organization_search_router)
# Register multi-segment member routes before the department detail route.
# Literal search routes use two segments to avoid being parsed as department IDs.
router.include_router(member_router)
router.include_router(department_router)
