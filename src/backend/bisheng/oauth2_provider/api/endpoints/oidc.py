"""Standard OAuth 2.0 / OIDC Provider endpoints (discovery, JWKS, authorize, consent, token, userinfo, revoke)."""

from __future__ import annotations

import base64
from urllib.parse import unquote

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.oauth2_provider import (
    OAuth2InvalidClientAuthError,
    OAuth2InvalidRequestError,
    OAuth2UnsupportedGrantTypeError,
)
from bisheng.common.schemas.api import UnifiedResponseModel, resp_200
from bisheng.oauth2_provider.api.endpoints.exchange import parse_exchange
from bisheng.oauth2_provider.api.protocol import OAuth2ProtocolRoute
from bisheng.oauth2_provider.domain.schemas.auth import (
    OAuth2ConsentDecision,
    OAuth2ConsentDecisionResponse,
    OAuth2ConsentDetails,
    OAuth2TokenResponse,
    OAuth2UserInfoResponse,
)
from bisheng.oauth2_provider.domain.schemas.exchange import EXCHANGE_GRANT_TYPE
from bisheng.oauth2_provider.domain.services.exchange_service import event
from bisheng.oauth2_provider.runtime import OAuth2ProviderRuntime, get_oauth2_runtime

public_router = APIRouter(prefix="/oauth2", tags=["OAuth2 Provider"], route_class=OAuth2ProtocolRoute)
consent_router = APIRouter(prefix="/oauth2", tags=["OAuth2 Provider"])


def resolve_public_origin(request: Request) -> str:
    from bisheng.common.services.config_service import settings

    dsh_public = getattr(getattr(settings, "dsh", None), "platform_public_url", None)
    if dsh_public:
        return str(dsh_public).rstrip("/")
    open_api_public = getattr(getattr(settings, "open_api", None), "public_base_url", None)
    if open_api_public:
        return str(open_api_public).rstrip("/")
    forwarded_proto = request.headers.get("x-forwarded-proto")
    scheme = forwarded_proto.split(",")[0].strip() if forwarded_proto else request.url.scheme
    forwarded_host = request.headers.get("x-forwarded-host")
    host = forwarded_host.split(",")[0].strip() if forwarded_host else request.headers.get("host", request.url.netloc)
    return f"{scheme}://{host}".rstrip("/")


def _parse_basic_client_auth(request: Request) -> tuple[str | None, str | None]:
    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.lower().startswith("basic "):
        return None, None
    encoded = auth_header.split(" ", 1)[1].strip()
    try:
        decoded = base64.b64decode(encoded).decode("utf-8")
        if ":" not in decoded:
            raise ValueError("Missing colon")
        cid, csec = decoded.split(":", 1)
        return unquote(cid), unquote(csec)
    except Exception as exc:
        raise OAuth2InvalidClientAuthError() from exc


async def _parse_form_or_json(request: Request) -> dict[str, str]:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type == "application/json":
        data = await request.json()
        if not isinstance(data, dict):
            raise OAuth2InvalidRequestError()
        return {str(k): str(v) for k, v in data.items() if v is not None}
    form = await request.form()
    return {str(k): str(v) for k, v in form.items() if v is not None}


async def _try_browser_user(request: Request):
    """Use the ordinary browser admission checks even on this public endpoint."""
    from loguru import logger
    from starlette.exceptions import HTTPException

    from bisheng.common.errcode.base import BaseErrorCode
    from bisheng.common.exceptions.auth import AuthJWTException
    from bisheng.user.domain.services.auth import AuthJwt
    from bisheng.utils.http_middleware import _apply_token_version_and_visible

    auth = AuthJwt(req=request)
    token = auth.request_access_token()
    if not token:
        return None
    try:
        subject = auth.get_subject(token=token)
        denial = await _apply_token_version_and_visible(request, token, decoded_subject=subject)
        if denial is not None:
            return None
        user = await UserPayload.get_login_user(auth)
        return int(user.tenant_id), int(user.user_id)
    except (AuthJWTException, BaseErrorCode, HTTPException):
        # Invalid credentials fall back to interactive login, without granting a code.
        logger.debug("OAuth auto-approval requires a current browser identity")
        return None


@public_router.get("/openid-metadata")
async def openid_metadata(request: Request, runtime: OAuth2ProviderRuntime = Depends(get_oauth2_runtime)):
    return runtime.auth.build_openid_metadata(resolve_public_origin(request))


@public_router.get("/jwks")
async def jwks(runtime: OAuth2ProviderRuntime = Depends(get_oauth2_runtime)):
    return await runtime.keys.get_jwks()


@public_router.get("/authorize")
async def authorize(
    request: Request,
    client_id: str = Query(..., min_length=1, max_length=128),
    redirect_uri: str = Query(..., min_length=1, max_length=2048),
    response_type: str = Query("code"),
    scope: str | None = Query(default="openid profile"),
    state: str | None = Query(default=None, max_length=512),
    code_challenge: str | None = Query(default=None, max_length=128),
    code_challenge_method: str | None = Query(default=None, max_length=16),
    nonce: str | None = Query(default=None, max_length=256),
    device_name: str | None = Query(default=None, max_length=128),
    runtime: OAuth2ProviderRuntime = Depends(get_oauth2_runtime),
):
    request_id, client, _ = await runtime.auth.start_authorization(
        client_id=client_id,
        redirect_uri=redirect_uri,
        response_type=response_type,
        scope=scope,
        state=state,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        nonce=nonce,
        device_name=device_name,
    )
    if not client.require_consent:
        browser = await _try_browser_user(request)
        if browser is not None:
            tenant_id, user_id = browser
            callback = await runtime.auth.approve_request_direct(
                request_id=request_id,
                user_id=user_id,
                tenant_id=tenant_id,
            )
            return RedirectResponse(url=callback, status_code=302)
    origin = resolve_public_origin(request)
    return RedirectResponse(url=f"{origin}/oauth-consent?request_id={request_id}", status_code=302)


@consent_router.get("/consent/{request_id}", response_model=UnifiedResponseModel[OAuth2ConsentDetails])
async def get_consent(
    request_id: str,
    user: UserPayload = Depends(UserPayload.get_login_user),
    runtime: OAuth2ProviderRuntime = Depends(get_oauth2_runtime),
):
    _ = user
    details = await runtime.auth.get_consent_details(request_id)
    return resp_200(data=details)


@consent_router.post("/consent/{request_id}", response_model=UnifiedResponseModel[OAuth2ConsentDecisionResponse])
async def submit_consent(
    request_id: str,
    body: OAuth2ConsentDecision,
    request: Request,
    user: UserPayload = Depends(UserPayload.get_login_user),
    runtime: OAuth2ProviderRuntime = Depends(get_oauth2_runtime),
):
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise OAuth2InvalidRequestError(msg="Content-Type must be application/json")
    origin_header = request.headers.get("origin")
    if origin_header and origin_header.rstrip("/") != resolve_public_origin(request):
        raise OAuth2InvalidRequestError(msg="Origin mismatch")
    result = await runtime.auth.submit_consent(
        request_id=request_id,
        user_id=int(user.user_id),
        tenant_id=int(user.tenant_id),
        decision=body.decision,
    )
    return resp_200(data=result)


@public_router.post("/token", response_model=OAuth2TokenResponse)
async def token(request: Request, runtime: OAuth2ProviderRuntime = Depends(get_oauth2_runtime)):
    await request.body()  # Preserve raw fields for strict exchange parsing after grant dispatch.
    params = await _parse_form_or_json(request)
    grant_type = params.get("grant_type")
    if grant_type == EXCHANGE_GRANT_TYPE:
        try:
            params = await parse_exchange(request)
            basic_id, basic_secret = _parse_basic_client_auth(request)
        except BaseErrorCode as exc:
            event("request_denied_" + str(exc.code))
            raise
    else:
        basic_id, basic_secret = _parse_basic_client_auth(request)
    client_id = basic_id or params.get("client_id")
    client_secret = basic_secret if basic_id is not None else params.get("client_secret")
    origin = resolve_public_origin(request)

    if grant_type == EXCHANGE_GRANT_TYPE:
        result = await runtime.exchange.exchange_token(
            origin=origin,
            client_id=client_id,
            client_secret=client_secret,
            subject_token=params.get("subject_token"),
            subject_token_type=params.get("subject_token_type"),
            audience=params.get("audience"),
            scope=params.get("scope"),
            requested_token_type=params.get("requested_token_type"),
        )
        return JSONResponse(content=result)

    if grant_type == "authorization_code":
        code = params.get("code")
        redirect_uri = params.get("redirect_uri")
        if not code or not client_id or not redirect_uri:
            raise OAuth2InvalidRequestError(msg="Missing required parameters for authorization_code grant")
        result = await runtime.auth.exchange_code(
            origin=origin,
            code=code,
            client_id=client_id,
            redirect_uri=redirect_uri,
            code_verifier=params.get("code_verifier"),
            client_secret=client_secret,
        )
        return JSONResponse(content=result.model_dump(exclude_none=True))

    if grant_type == "refresh_token":
        refresh_token_val = params.get("refresh_token")
        if not refresh_token_val:
            raise OAuth2InvalidRequestError(msg="Missing refresh_token")
        result = await runtime.auth.refresh_access_token(
            origin=origin,
            refresh_token=refresh_token_val,
            client_id=client_id,
            client_secret=client_secret,
        )
        return JSONResponse(content=result.model_dump(exclude_none=True))

    raise OAuth2UnsupportedGrantTypeError()


@public_router.get("/userinfo", response_model=OAuth2UserInfoResponse)
async def userinfo(request: Request, runtime: OAuth2ProviderRuntime = Depends(get_oauth2_runtime)):
    bearer = request.headers.get("authorization", "")
    result = await runtime.auth.userinfo(bearer)
    return JSONResponse(content=result.model_dump(exclude_none=True))


@public_router.post("/revoke", status_code=200)
async def revoke(request: Request, runtime: OAuth2ProviderRuntime = Depends(get_oauth2_runtime)):
    params = await _parse_form_or_json(request)
    basic_id, basic_secret = _parse_basic_client_auth(request)
    client_id = basic_id or params.get("client_id")
    client_secret = basic_secret if basic_id is not None else params.get("client_secret")
    await runtime.auth.revoke_token(
        token=params.get("token", ""),
        client_id=client_id,
        client_secret=client_secret,
    )
    return Response(status_code=200)
