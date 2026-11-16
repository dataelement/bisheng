"""F120 self-hosted WeCom SSO endpoints.

All three are anonymous (the middleware exempts ``/api/v1/user/wecom/``):
before login there is no session, and the callback proves itself with the
one-time ``state`` instead. Login state leaves the callback as a cookie — a
token in the redirect URL would end up in history, logs and Referer (INV-46).
"""

from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.schemas.api import UnifiedResponseModel, resp_200
from bisheng.common.services.config_service import settings
from bisheng.sso_sync.domain.services.wecom_login_service import (
    WeComLoginService,
    build_callback_url,
)
from bisheng.utils import get_request_ip

router = APIRouter(tags=["WeCom SSO"])

ACCESS_COOKIE_KEY = "access_token_cookie"


def _public_origin(request: Request) -> str:
    """Origin the browser used, honouring a reverse proxy in front of the API."""
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}"


def _with_error(return_to: str, code: int) -> str:
    """Append ``wecom_error`` to the login page the user is sent back to."""
    parsed = urlparse(return_to)
    separator = "&" if parsed.query else "?"
    return f"{return_to}{separator}wecom_error={code}"


def _error_redirect(origin: str, code: int) -> RedirectResponse:
    return RedirectResponse(_with_error(f"{origin}/", code), status_code=302)


@router.get(
    "/user/wecom/availability",
    response_model=UnifiedResponseModel[dict],
    summary="Whether the self-hosted WeCom login entry is available",
)
async def wecom_availability(request: Request):
    data = await WeComLoginService.availability(request.headers.get("user-agent"))
    return resp_200(data)


@router.get("/user/wecom/authorize", summary="Start a WeCom authorization")
async def wecom_authorize(
    request: Request,
    return_to: str | None = None,
    mode: str | None = None,
):
    origin = _public_origin(request)
    try:
        url = await WeComLoginService.authorize(
            return_to=return_to,
            force_mode=mode,
            user_agent=request.headers.get("user-agent"),
            public_origin=origin,
            callback_url=build_callback_url(origin),
        )
    except BaseErrorCode as exc:
        return RedirectResponse(
            _with_error(f"{origin}/", exc.code),
            status_code=302,
        )
    except HTTPException as exc:
        return _error_redirect(origin, int(exc.status_code))
    return RedirectResponse(url, status_code=302)


@router.get("/user/wecom/callback", summary="WeCom authorization callback")
async def wecom_callback(request: Request, code: str = "", state: str = ""):
    origin = _public_origin(request)
    try:
        return_to, token = await WeComLoginService.callback(
            code=code,
            state=state,
            request_ip=get_request_ip(request),
        )
    except BaseErrorCode as exc:
        return RedirectResponse(
            _with_error(f"{origin}/", exc.code),
            status_code=302,
        )
    except HTTPException as exc:
        # Disabled account (10620), concurrent login (19311) and the other
        # login-sync refusals arrive as HTTPExceptions; the login page renders
        # them from the shared api_errors copy instead of a JSON error body.
        return _error_redirect(origin, int(exc.status_code))

    response = RedirectResponse(return_to, status_code=302)
    _set_access_cookie(response, token)
    return response


def _set_access_cookie(response: RedirectResponse, token: str) -> None:
    """Hand the session to the browser.

    ``httponly=False`` on purpose: the platform mirrors the cookie value into
    ``localStorage.ws_token``, exactly as the password login already does, and a
    few components read that key. See design decision 2.
    """
    conf = settings.cookie_conf
    response.set_cookie(
        ACCESS_COOKIE_KEY,
        token,
        max_age=conf.max_age or (conf.jwt_token_expire_time + 3600),
        path=conf.path,
        domain=conf.domain,
        secure=conf.secure,
        httponly=False,
        samesite=conf.samesite,
    )
