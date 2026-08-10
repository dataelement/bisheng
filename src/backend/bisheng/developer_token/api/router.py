from fastapi import APIRouter

from bisheng.developer_token.api.endpoints.automotive_sheet_intro_sync import (
    router as automotive_sheet_intro_sync_router,
)
from bisheng.developer_token.api.endpoints.developer_token import router as developer_token_router

router = APIRouter(tags=["DeveloperToken"])
router.include_router(automotive_sheet_intro_sync_router)
router.include_router(developer_token_router)
