"""Agent runtime router aggregation (F078)."""

from fastapi import APIRouter

from bisheng.agent_runtime.api.endpoints.files import router as files_router

router = APIRouter(prefix="/agent-runtime", tags=["AgentRuntime"])
router.include_router(files_router)
