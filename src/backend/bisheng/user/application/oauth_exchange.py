"""Transport-free first-party session subjects for OAuth token exchange."""

import hmac
from datetime import datetime

from bisheng.common.errcode.platform_auth import PlatformAuthError
from bisheng.user.domain.const import FIRST_PARTY_CLIENT_IDS
from bisheng.user.domain.services.platform_transport import access_credential, require_csrf, require_origin
from bisheng.user.platform_auth_runtime import get_platform_auth, platform_auth_service


async def read_platform_exchange_subject(request, subject_token: str | None = None) -> dict:
    """Authenticate a first-party access token without exposing transport secrets.

    Any Cookie header makes this a browser request, even when the caller also
    supplies a body token. Native callers may supply a body token or Bearer.
    """
    authorization = request.headers.get("authorization")
    if authorization is not None and (not authorization.lower().startswith("bearer ") or not authorization[7:].strip()):
        raise PlatformAuthError("invalid_auth_request")
    if subject_token is not None and (not isinstance(subject_token, str) or not subject_token):
        raise PlatformAuthError("invalid_auth_request")

    selected = access_credential(request)
    # gateway=False ignores residual legacy/bootstrap fixed cookies after binding.
    # Only the selected platform Cookie, Bearer and explicit body token compete.
    candidates = [value for value in (selected, subject_token) if value]
    if any(not hmac.compare_digest(candidates[0], value) for value in candidates[1:]):
        raise PlatformAuthError("credential_conflict")
    token = selected or subject_token
    if not token:
        raise PlatformAuthError()

    if request.headers.get("sec-fetch-site") not in {None, "same-origin", "none"}:
        raise PlatformAuthError("csrf_rejected")
    if "origin" in request.headers:
        require_origin(request)

    service = get_platform_auth(request)
    metadata = await service.inspect(token)
    claims = service.decode(token)
    if claims["client_id"] not in FIRST_PARTY_CLIENT_IDS:
        raise PlatformAuthError()
    if "cookie" in request.headers:
        require_csrf(request, metadata)

    reference = {
        "kind": "platform_session",
        "user_id": int(claims["sub"]),
        "tenant_id": int(claims["tenant_id"]),
        "token_version": claims["token_version"],
        "expires_at": metadata["access_expires_at"],
        "session_id": claims["session_id"],
        "session_version": claims["session_version"],
    }
    return {
        "user_id": reference["user_id"],
        "tenant_id": reference["tenant_id"],
        "client_id": claims["client_id"],
        "expires_at": int(claims["exp"]),
        "session_expires_at": int(datetime.fromisoformat(metadata["session_expires_at"]).timestamp()),
        "reference": reference,
    }


async def validate_platform_exchange_reference(reference: dict) -> None:
    """Revalidate through the user-domain session authority at point of use."""
    await platform_auth_service().validate_reference(reference)
