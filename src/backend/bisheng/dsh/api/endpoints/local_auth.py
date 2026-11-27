"""Native Desktop login endpoints; the compatibility router has identical handlers."""

from typing import Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import Field

from bisheng.common.errcode.dsh import DshInvalidRequestError
from bisheng.dsh.access_runtime import get_logout_runtime, get_runtime
from bisheng.dsh.api.responses import DshRoute
from bisheng.dsh.domain.schemas.contracts import DshContract
from bisheng.dsh.request_origin import resolve_client_origin
from bisheng.user.application.dsh_session import (
    issue_desktop_session,
    logout_desktop_session,
    refresh_desktop_session,
)

router = APIRouter(prefix="/dsh", route_class=DshRoute)


class AuthorizationRequest(DshContract):
    client_id: Literal["dsh-desktop"]
    redirect_uri: str = Field(min_length=1, max_length=2048)
    code_challenge: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")
    code_challenge_method: Literal["S256"]
    state: str = Field(pattern=r"^[A-Za-z0-9_-]{32,128}$")
    device_name: str | None = Field(default=None, min_length=1, max_length=100)
    client_version: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")


class TokenRequest(DshContract):
    grant_type: Literal["identity_ticket", "refresh_token"]
    identity_ticket: str | None = Field(default=None, max_length=256)
    auth_id: str | None = Field(default=None, max_length=36)
    code_verifier: str | None = Field(default=None, max_length=128)
    refresh_token: str | None = Field(default=None, max_length=256)


class LogoutRequest(DshContract):
    refresh_token: str | None = Field(default=None, max_length=256)


@router.post("/authorizations")
async def authorization(body: AuthorizationRequest, request: Request, runtime=Depends(get_runtime)):
    await runtime.authorizations.rate("authorization", request.client.host if request.client else "unknown")
    return await runtime.authorizations.create(body, origin=await resolve_client_origin(request, runtime.settings))


@router.post("/token")
async def token(body: TokenRequest, request: Request, response: Response, runtime=Depends(get_runtime)):
    response.headers["Cache-Control"] = "no-store"
    await runtime.authorizations.rate("token", request.client.host if request.client else "unknown")
    if body.grant_type == "refresh_token":
        if not body.refresh_token or any(
            value is not None for value in (body.identity_ticket, body.auth_id, body.code_verifier)
        ):
            raise DshInvalidRequestError()
        return await refresh_desktop_session(request, runtime, body.refresh_token)
    if body.refresh_token is not None or not all((body.identity_ticket, body.auth_id, body.code_verifier)):
        raise DshInvalidRequestError()
    binding = await runtime.authorizations.resolve(body.auth_id)
    runtime.authorizations.verify(binding["challenge"], body.code_verifier)
    identity = await runtime.identity.redeem(
        body.identity_ticket,
        {
            "auth_id": body.auth_id,
            "client_id": binding["client_id"],
            "redirect_uri": binding["redirect_uri"],
            "code_challenge": binding["challenge"],
        },
    )
    return await issue_desktop_session(request, identity, binding)


@router.post("/logout", status_code=204)
async def logout(request: Request, body: LogoutRequest | None = None, runtime=Depends(get_logout_runtime)):
    headers = request.headers.getlist("authorization")
    refresh = body.refresh_token if body else None
    if len(headers) > 1 or bool(headers) == bool(refresh):
        raise DshInvalidRequestError()
    await logout_desktop_session(request, runtime, credential=refresh or headers[0], refresh=bool(refresh))
    return Response(status_code=204)
