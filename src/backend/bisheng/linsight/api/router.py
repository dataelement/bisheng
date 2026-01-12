from fastapi import APIRouter
from .endpoints.linsight import router as linsight_router

router = APIRouter(prefix="/linsight", tags=["Inspiration"])

router.include_router(linsight_router)

__all__ = ["router"]
