"""Org sync module router aggregation.

Part of F009-org-sync.
"""

from fastapi import APIRouter

from bisheng.org_sync.api.endpoints.sync_config import router as config_router
from bisheng.org_sync.api.endpoints.sync_exec import router as exec_router

router = APIRouter(prefix='/org-sync', tags=['Org Sync'])
router.include_router(config_router)
router.include_router(exec_router)
