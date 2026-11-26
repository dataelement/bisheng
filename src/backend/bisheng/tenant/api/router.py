"""Tenant module router aggregation.

Part of F010-tenant-management-ui.
"""

from bisheng.common.request_scope import RequestScope as S
from bisheng.common.request_scope import ScopedAPIRouter as APIRouter
from bisheng.common.request_scope import scope_overrides
from bisheng.tenant.api.endpoints.tenant_admin import router as admin_router
from bisheng.tenant.api.endpoints.tenant_crud import router as crud_router
from bisheng.tenant.api.endpoints.tenant_mount import router as mount_router
from bisheng.tenant.api.endpoints.tenant_users import router as users_router
from bisheng.tenant.api.endpoints.user_tenant import router as user_tenant_router

scope_overrides(user_tenant_router, S.PUBLIC, "switch_tenant_deprecated")

router = APIRouter(tags=["Tenant"])

# Admin endpoints: /tenants/*
router.include_router(crud_router, request_scope=S.PLATFORM, prefix="/tenants")
router.include_router(users_router, request_scope=S.PLATFORM, prefix="/tenants")
# F013: Child Tenant admin CRUD at /tenants/{id}/admins
router.include_router(admin_router, request_scope=S.PLATFORM, prefix="/tenants")

# User-facing endpoints: /user/*
router.include_router(user_tenant_router, request_scope=S.IDENTITY, prefix="/user")

# v2.5.1 F011: mount/unmount/migrate endpoints. These live at both
# /departments/*/mount-tenant and /tenants/*/resources/migrate-from-root
# so include without a prefix and let the handlers own the full path.
router.include_router(mount_router, request_scope=S.PLATFORM)
