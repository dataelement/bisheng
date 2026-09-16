"""Route lookup — the app-proxy's only question to the manager (D5.1, T027)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from runtime_manager.auth import verify_hmac
from runtime_manager.config import get_config
from runtime_manager.preview import PreviewService
from runtime_manager.routing import RoutingService

router = APIRouter(prefix="/v1", tags=["routing"], dependencies=[Depends(verify_hmac)])


@router.get("/apps/{app_id}/route")
async def get_route(app_id: str) -> dict:
    """``{upstream, version_id, generation}`` — a bridge address, never a name.

    404 is a legitimate, expected answer (no instance / stopped): the app-proxy
    turns it into the product's "已停用 / 不存在" page rather than retrying.
    """
    return RoutingService(get_config()).get_route(app_id).to_response()


@router.get("/previews/{session_id}/route")
async def get_preview_route(session_id: str) -> dict:
    """Where an approval-time preview is answering right now (F055 AC-26).

    Same shape as the app route so the app-proxy keeps one forwarding path, and
    the same 404 meaning: reclaimed, timed out or never started are one answer
    — the proxy renders 「不存在」 for it rather than retrying forever.
    """
    return PreviewService(get_config()).route(session_id)
