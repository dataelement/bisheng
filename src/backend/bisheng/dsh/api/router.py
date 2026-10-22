"""F062 router composition; endpoint modules own the dedicated auth policies."""

from fastapi import APIRouter

from bisheng.dsh.api.endpoints.admin import router as admin_router
from bisheng.dsh.api.endpoints.capabilities import router as capability_router
from bisheng.dsh.api.endpoints.identity import router as identity_router
from bisheng.dsh.api.endpoints.local_auth import router as local_auth_router
from bisheng.dsh.api.endpoints.model_audit_admin import router as model_audit_router
from bisheng.dsh.api.endpoints.model_audit_title import router as model_audit_title_router
from bisheng.dsh.api.endpoints.models import router as model_router
from bisheng.dsh.api.endpoints.self_service import router as self_router
from bisheng.dsh.api.endpoints.settings import router as settings_router
from bisheng.dsh.api.endpoints.tools import router as tool_router
from bisheng.dsh.api.endpoints.unified_policy import router as unified_policy_router
from bisheng.dsh.api.endpoints.web_session import router as web_session_router
from bisheng.dsh.api.endpoints.work import router as work_router

router = APIRouter()
router.include_router(local_auth_router)
router.include_router(capability_router)
router.include_router(work_router)
router.include_router(unified_policy_router)
router.include_router(web_session_router)

compatibility_router = APIRouter(prefix="/api")
compatibility_router.include_router(local_auth_router)
router.include_router(self_router)
router.include_router(identity_router)
router.include_router(model_router)
router.include_router(admin_router)
router.include_router(settings_router)
router.include_router(model_audit_router)
router.include_router(model_audit_title_router)
router.include_router(tool_router)
