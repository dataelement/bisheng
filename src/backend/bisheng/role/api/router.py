"""Role module router aggregation.

Part of F005-role-menu-quota.
"""

from fastapi import APIRouter

from bisheng.role.api.endpoints.role import router as role_router
from bisheng.role.api.endpoints.role_access import router as menu_router
from bisheng.role.api.endpoints.quota import router as quota_router

router = APIRouter(tags=['Role'])
router.include_router(role_router)
router.include_router(menu_router)
router.include_router(quota_router)
