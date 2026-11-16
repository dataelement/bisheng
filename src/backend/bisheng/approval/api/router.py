from bisheng.common.request_scope import RequestScope as S
from bisheng.common.request_scope import ScopedAPIRouter as APIRouter

from .endpoints.approval import router as legacy_router
from .endpoints.approval_admin import router as admin_router
from .endpoints.approval_user import router as user_router

router = APIRouter()
router.include_router(user_router, request_scope=S.PERSONAL)
router.include_router(admin_router, request_scope=S.TENANT)
router.include_router(legacy_router, request_scope=S.PERSONAL)

__all__ = ["router"]
