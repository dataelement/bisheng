"""Tenant module router aggregation.

Part of F010-tenant-management-ui.
"""

from fastapi import APIRouter

from bisheng.tenant.api.endpoints.tenant_crud import router as crud_router
from bisheng.tenant.api.endpoints.tenant_users import router as users_router
from bisheng.tenant.api.endpoints.user_tenant import router as user_tenant_router

router = APIRouter(tags=['Tenant'])

# Admin endpoints: /tenants/*
router.include_router(crud_router, prefix='/tenants')
router.include_router(users_router, prefix='/tenants')

# User-facing endpoints: /user/*
router.include_router(user_tenant_router, prefix='/user')
