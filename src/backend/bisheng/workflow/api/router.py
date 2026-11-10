from fastapi import APIRouter

from bisheng.workflow.api.endpoints.platform_agent import router as platform_agent_router

from bisheng.workflow.api.endpoints.platform_knowledge import router as platform_knowledge_router

router = APIRouter(prefix="/workflow", tags=["Workflow"])
router.include_router(platform_agent_router)
router.include_router(platform_knowledge_router)
