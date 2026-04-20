"""Tenant module router aggregation.

Part of F010-tenant-management-ui.
"""

from fastapi import APIRouter

from bisheng.tenant.api.endpoints.resource_owner_transfer import (
    router as owner_transfer_router,
)
from bisheng.tenant.api.endpoints.resource_share import router as resource_share_router
from bisheng.tenant.api.endpoints.tenant_admin import router as admin_router
from bisheng.tenant.api.endpoints.tenant_crud import router as crud_router
from bisheng.tenant.api.endpoints.tenant_mount import router as mount_router
from bisheng.tenant.api.endpoints.tenant_users import router as users_router
from bisheng.tenant.api.endpoints.user_tenant import router as user_tenant_router

router = APIRouter(tags=['Tenant'])

# Admin endpoints: /tenants/*
router.include_router(crud_router, prefix='/tenants')
router.include_router(users_router, prefix='/tenants')
# F013: Child Tenant admin CRUD at /tenants/{id}/admins
router.include_router(admin_router, prefix='/tenants')

# User-facing endpoints: /user/*
router.include_router(user_tenant_router, prefix='/user')

# v2.5.1 F011: mount/unmount/migrate endpoints. These live at both
# /departments/*/mount-tenant and /tenants/*/resources/migrate-from-root
# so include without a prefix and let the handlers own the full path.
router.include_router(mount_router)

# v2.5.1 F018: owner-transfer endpoints under /tenants/*/resources/* —
# handlers own the full path (same convention as F011 mount_router).
router.include_router(owner_transfer_router)

# v2.5.1 F017: resource share toggle at /resources/{type}/{id}/share —
# handler owns the full path (same convention as mount / owner-transfer).
router.include_router(resource_share_router)
