"""Permission module router registration."""

from fastapi import APIRouter

from bisheng.permission.api.endpoints.permission_check import router as check_router
from bisheng.permission.api.endpoints.resource_permission import router as resource_router

router = APIRouter(prefix='/permissions', tags=['Permission'])
router.include_router(check_router)
router.include_router(resource_router)
