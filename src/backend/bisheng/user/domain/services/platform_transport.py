"""Browser credential selection and CSRF; native JSON credentials stay explicit."""

import hmac
import re

from bisheng.common.errcode.platform_auth import PlatformAuthError
from bisheng.user.domain.services.platform_origin import public_origin


def selected_sid(connection):
    selector = connection.headers.get("x-platform-session")
    if selector and connection.url.path in {"/api/v1/auth/logout", "/api/v1/auth/logout-all", "/api/v1/auth/csrf"}:
        if not re.fullmatch(r"[a-f0-9]{32}", selector):
            raise PlatformAuthError("invalid_auth_request")
        return selector
    sid = connection.cookies.get("platform_session_hint", "")
    return sid if re.fullmatch(r"[a-f0-9]{32}", sid) else None


def access_credential(connection, *, gateway=False):
    sid = selected_sid(connection)
    cookie = connection.cookies.get(f"platform_access_{sid}") if sid else None
    bearer = connection.headers.get("authorization", "")
    bearer = bearer[7:].strip() if bearer.lower().startswith("bearer ") else None
    if cookie and bearer and not hmac.compare_digest(cookie, bearer):
        raise PlatformAuthError("credential_conflict")
    if gateway:
        fixed = connection.cookies.get("access_token_cookie")
        if fixed:
            import jwt

            try:
                payload = jwt.decode(fixed, options={"verify_signature": False})
                if payload.get("bootstrap_only"):
                    if cookie and payload.get("session_id") == sid:
                        return cookie or bearer
                    return fixed
            except jwt.PyJWTError:
                # A malformed old cookie must not hide an explicit valid session.
                pass
    return cookie or bearer


def refresh_credential(connection):
    sid = selected_sid(connection)
    return connection.cookies.get(f"platform_refresh_{sid}") if sid else None


def require_origin(request):
    origin = public_origin(request)
    if request.headers.get("origin") != origin or request.headers.get("sec-fetch-site") not in {
        None,
        "same-origin",
        "none",
    }:
        raise PlatformAuthError("csrf_rejected")


def require_csrf(request, metadata):
    require_origin(request)
    supplied = request.headers.get("x-csrf-token", "")
    if not hmac.compare_digest(supplied, metadata["csrf_token"]):
        raise PlatformAuthError("csrf_rejected")


def deliver(response, request, data, *, native=False):
    response.headers["Cache-Control"] = "no-store"
    public = dict(data)
    if native:
        return public
    sid = data["session_id"]
    options = {"httponly": True, "secure": public_origin(request).startswith("https://"), "samesite": "lax"}
    response.set_cookie(f"platform_access_{sid}", data["access_token"], max_age=data["expires_in"], path="/", **options)
    if "refresh_token" in data:
        response.set_cookie(
            f"platform_refresh_{sid}",
            data["refresh_token"],
            max_age=data["cookie_retention_seconds"],
            path="/api/v1/auth",
            **options,
        )
    public.pop("refresh_token", None)
    public.pop("access_token", None)
    return public
