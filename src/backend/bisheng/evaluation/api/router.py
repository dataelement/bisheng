from fastapi import APIRouter

from bisheng.evaluation.api.endpoints.evaluation import router as evaluation_router

router = APIRouter()
router.include_router(evaluation_router)
