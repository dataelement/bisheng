from .endpoints.approval import router as legacy_router
from .endpoints.approval_admin import router as admin_router
from .endpoints.approval_user import router as user_router
from .endpoints.shougang_approval import router as shougang_router
from fastapi import APIRouter

router = APIRouter()
router.include_router(user_router)
router.include_router(admin_router)
router.include_router(legacy_router)
router.include_router(shougang_router)

__all__ = ['router']
