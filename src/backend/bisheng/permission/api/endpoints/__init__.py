"""F048 permission HTTP endpoint routers."""

from bisheng.permission.api.endpoints.catalog import router as catalog_router
from bisheng.permission.api.endpoints.decision import router as decision_router
from bisheng.permission.api.endpoints.grant import router as grant_router

__all__ = (
    "catalog_router",
    "decision_router",
    "grant_router",
)
