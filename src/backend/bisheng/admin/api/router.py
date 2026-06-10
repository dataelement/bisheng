"""F019-admin-tenant-scope router aggregation.

Exposes the ``/admin/*`` namespace. Currently hosts only the tenant-scope
endpoints; future admin-only operations (scope history queries, system
diagnostics) can attach to the same router.
"""

from fastapi import APIRouter

from bisheng.admin.api.endpoints.tenant_scope import router as tenant_scope_router
from bisheng.developer_token.api.router import router as developer_token_router


router = APIRouter(tags=['Admin'])
router.include_router(tenant_scope_router)
router.include_router(developer_token_router)
