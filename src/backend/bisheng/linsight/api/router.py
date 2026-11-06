from fastapi import APIRouter

from .endpoints.linsight import router as linsight_router
from .endpoints.personal_skill import router as personal_skill_router
from .endpoints.skill import router as skill_router

router = APIRouter(prefix="/linsight", tags=["Inspiration"])

router.include_router(linsight_router)
# Literal skill paths (center, candidates, personal) must be registered
# before /skill/{name}, or those words are treated as skill identifiers.
router.include_router(personal_skill_router)
router.include_router(skill_router)

__all__ = ["router"]
