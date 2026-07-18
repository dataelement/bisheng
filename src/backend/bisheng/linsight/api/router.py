from fastapi import APIRouter

from .endpoints.linsight import router as linsight_router
from .endpoints.skill import router as skill_router

router = APIRouter(prefix="/linsight", tags=["Inspiration"])

router.include_router(linsight_router)
router.include_router(skill_router)

__all__ = ["router"]
