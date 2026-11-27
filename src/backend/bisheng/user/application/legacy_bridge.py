"""Targeted browser adapter; never treat ordinary old web tokens as host grants."""

import hashlib
from datetime import UTC, datetime

import jwt

from bisheng.common.errcode.platform_auth import PlatformAuthError


async def legacy_host_metadata(request):
    token = request.cookies.get("access_token_cookie")
    if not token:
        raise PlatformAuthError()
    from bisheng.dsh.domain.services.web_session import validate_web_session
    from bisheng.user.domain.services.auth import AuthJwt

    auth = AuthJwt(req=request)
    subject = auth.decode_jwt_token(token)
    if "dsh_web_session" not in subject:
        raise PlatformAuthError("legacy_web_token_rejected")
    await validate_web_session(request, subject)
    claims = jwt.decode(token, auth.jwt_secret, algorithms=["HS256"], issuer=auth.cookie_conf.jwt_iss)
    expiry = datetime.fromtimestamp(claims["exp"], UTC).isoformat()
    return {
        "session_id": hashlib.sha256(subject["dsh_web_session"].encode()).hexdigest()[:32],
        "access_expires_at": expiry,
        "session_expires_at": expiry,
        "refresh_expires_at": expiry,
        "expires_in": max(0, claims["exp"] - int(datetime.now(UTC).timestamp())),
        "refresh_mode": "host",
        "auth_source": "legacy_dsh",
        "delivery_state": "BOUND",
        "user": {"id": subject["user_id"], "user_name": subject["user_name"]},
        "tenant": {"id": subject["tenant_id"], "name": ""},
        "default_entry": "/workspace",
    }
