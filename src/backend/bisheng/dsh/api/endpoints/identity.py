"""Public discovery, browser authorization and HMAC-only identity exchange."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.dsh import DshInvalidAccessTokenError, DshInvalidRequestError
from bisheng.common.schemas.api import resp_200
from bisheng.dsh.api.dependencies import DshRuntime, get_runtime, get_settings
from bisheng.dsh.api.responses import DshRoute
from bisheng.dsh.config import DshSettings
from bisheng.dsh.domain.schemas.contracts import DshContract, SubjectId
from bisheng.dsh.domain.services.identity import BrowserIdentity

router = APIRouter(route_class=DshRoute)
browser_user = UserPayload.get_login_user


class AuthorizeRequest(DshContract):
    auth_id: str = Field(min_length=1, max_length=128)
    decision: Literal["approve", "deny"] = "approve"


class RedeemRequest(DshContract):
    auth_id: str = Field(min_length=1, max_length=128)
    identity_ticket: str = Field(min_length=1, max_length=256)
    client_id: str = Field(min_length=1, max_length=64)
    redirect_uri: str = Field(min_length=1, max_length=2048)
    code_challenge: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")


class CheckRequest(DshContract):
    installation_id: str = Field(min_length=1, max_length=64)
    tenant_id: SubjectId
    user_id: SubjectId


@router.get("/dsh/config")
async def config(settings: DshSettings = Depends(get_settings)):
    if not settings.enabled:
        return {"enabled": False}
    return {"enabled": True, "client_id": settings.client_id, "contract_version": settings.contract_version}


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


async def require_service(request: Request, runtime: DshRuntime = Depends(get_runtime)) -> DshRuntime:
    required = ("x-dsh-installation-id", "x-dsh-key-id", "x-dsh-timestamp", "x-dsh-nonce", "x-dsh-signature")
    if any(len(request.headers.getlist(name)) != 1 for name in required) or request.url.query:
        raise DshInvalidAccessTokenError()
    body = await request.body()
    if len(body) > 65536:
        raise DshInvalidRequestError()
    await runtime.inbound_auth.verify(request.method, request.url.path, body, request.headers)
    return runtime


@router.post("/internal/dsh/identity/redeem")
async def redeem(body: RedeemRequest, runtime: DshRuntime = Depends(require_service)):
    binding = body.model_dump(exclude={"identity_ticket"})
    snapshot = await runtime.identity.redeem(body.identity_ticket, binding)
    return snapshot.model_dump(exclude_none=not snapshot.active)


@router.post("/internal/dsh/identity/check")
async def check(body: CheckRequest, runtime: DshRuntime = Depends(require_service)):
    if body.installation_id != runtime.settings.installation_id:
        raise DshInvalidAccessTokenError()
    snapshot = await runtime.identity.check(body.tenant_id, body.user_id)
    return snapshot.model_dump(exclude_none=not snapshot.active)
