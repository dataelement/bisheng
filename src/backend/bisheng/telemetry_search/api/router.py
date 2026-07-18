from fastapi import APIRouter

from .endpoints import dashboard

router = APIRouter(prefix="/telemetry", tags=["TelemetrySearch"])

router.include_router(dashboard.router)

__all__ = ["router"]
