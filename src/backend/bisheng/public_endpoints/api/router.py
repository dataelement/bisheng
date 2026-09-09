"""Exact public v3 allowlist."""

from fastapi import APIRouter, Depends

from bisheng.public_endpoints.api.dependencies import verify_public_access
from bisheng.public_endpoints.api.endpoints.assistant import router as assistant_router
from bisheng.public_endpoints.api.endpoints.chat import router as chat_router
from bisheng.public_endpoints.api.endpoints.flow import router as flow_router
from bisheng.public_endpoints.api.endpoints.workflow import router as workflow_router

router_public = APIRouter(
    prefix="/api/v3",
    dependencies=[Depends(verify_public_access)],
)
router_public.include_router(workflow_router)
router_public.include_router(assistant_router)
router_public.include_router(flow_router)
router_public.include_router(chat_router)

__all__ = ["router_public"]
