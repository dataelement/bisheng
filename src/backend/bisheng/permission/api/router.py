"""Permission module router registration."""

from fastapi import APIRouter

from bisheng.permission.api.endpoints.catalog import router as catalog_router
from bisheng.permission.api.endpoints.decision import router as decision_router
from bisheng.permission.api.endpoints.grant import router as grant_router

router = APIRouter(prefix='/permissions', tags=['Permission'])
router.include_router(catalog_router)
router.include_router(grant_router)
router.include_router(decision_router)
