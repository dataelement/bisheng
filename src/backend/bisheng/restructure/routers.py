from fastapi import APIRouter

from bisheng.restructure.assistants.routers import assistant_router

router = APIRouter()
router.include_router(assistant_router)
