"""Aggregate router for F014 SSO sync endpoints."""

from fastapi import APIRouter

from bisheng.sso_sync.api.endpoints.departments_sync import (
    router as departments_sync_router,
)
from bisheng.sso_sync.api.endpoints.gateway_wecom_org_sync import (
    router as gateway_wecom_org_sync_router,
)
from bisheng.sso_sync.api.endpoints.login_sync import (
    router as login_sync_router,
)


router = APIRouter()
router.include_router(login_sync_router)
router.include_router(departments_sync_router)
router.include_router(gateway_wecom_org_sync_router)
