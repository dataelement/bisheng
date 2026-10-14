"""E+ API router aggregation."""

from fastapi import APIRouter

from bisheng.eplus.api.endpoints.bot_config import router as bot_config_router

router = APIRouter(prefix="/eplus", tags=["E+ Robot"])
router.include_router(bot_config_router)
