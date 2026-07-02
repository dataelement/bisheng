from fastapi import APIRouter

from bisheng.shougang_portal_config.api.endpoints.portal_config import (
    router as portal_config_router,
)

router = APIRouter()
router.include_router(portal_config_router)
