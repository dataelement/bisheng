"""F062 router composition; endpoint modules own the dedicated auth policies."""

from fastapi import APIRouter

from bisheng.dsh.api.endpoints.admin import router as admin_router
from bisheng.dsh.api.endpoints.identity import router as identity_router
from bisheng.dsh.api.endpoints.models import router as model_router
from bisheng.dsh.api.endpoints.settings import router as settings_router

router = APIRouter()
router.include_router(identity_router)
router.include_router(model_router)
router.include_router(admin_router)
router.include_router(settings_router)
