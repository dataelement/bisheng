from fastapi import APIRouter

from bisheng.memory.api.endpoints.memory import router as memory_endpoint_router

router = APIRouter(prefix="/memory", tags=["Memory"])
router.include_router(memory_endpoint_router)
