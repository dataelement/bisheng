from fastapi import APIRouter

from bisheng.api_rate_limit.api.endpoints.api_rate_limit import router as config_router

router = APIRouter()
router.include_router(config_router)
