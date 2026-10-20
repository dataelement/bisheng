"""Public discovery and native browser authorization."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.dsh import DshInvalidRequestError
from bisheng.common.schemas.api import resp_200
from bisheng.dsh.api.dependencies import DshRuntime, get_runtime, get_settings
from bisheng.dsh.api.responses import DshRoute
from bisheng.dsh.config import DshSettings
from bisheng.dsh.domain.schemas.contracts import DshContract
from bisheng.dsh.domain.schemas.model_audit_context import AUDIT_FIELDS
from bisheng.dsh.domain.services.identity import BrowserIdentity
from bisheng.dsh.domain.services.settings import DshSettingsService

router = APIRouter(route_class=DshRoute)
browser_user = UserPayload.get_login_user


class AuthorizeRequest(DshContract):
    auth_id: str = Field(min_length=1, max_length=128)
    decision: Literal["approve", "deny"] = "approve"


@router.get("/dsh/config")
async def config(settings: DshSettings = Depends(get_settings)):
    if not settings.enabled:
        return {"enabled": False}
    if not (await DshSettingsService().read()).enabled:
        return {"enabled": False}
    return {
        "enabled": True,
        "client_id": settings.client_id,
        "contract_version": settings.contract_version,
        "audit_context": {"fields": list(AUDIT_FIELDS)},
        "audit_conversation_title": {"version": 1},
    }


@router.post("/dsh/authorize")
async def authorize(
    body: AuthorizeRequest, request: Request, user=Depends(browser_user), runtime: DshRuntime = Depends(get_runtime)
):
    # Exact Origin plus JSON-only POST blocks browser CSRF; never trust Referer as a fallback.
    if (
        request.headers.get("origin") != runtime.settings.platform_public_url
        or request.headers.get("sec-fetch-site", "same-origin") != "same-origin"
    ):
        raise HTTPException(403, "Invalid browser origin")
    if request.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json":
        raise DshInvalidRequestError()
    result = await runtime.identity.authorize(
        BrowserIdentity(str(user.tenant_id), str(user.user_id)), body.auth_id, decision=body.decision
    )
    return resp_200(data=result)
