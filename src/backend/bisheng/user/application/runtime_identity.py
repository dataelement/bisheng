"""Current verified identity value for server-owned delayed web work."""

from datetime import datetime

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.user.domain.repositories.runtime_identity import current_runtime_person


async def resolve_web_runtime_identity(reference):
    try:
        if reference["kind"] != "web_session" or datetime.fromisoformat(reference["expires_at"]) <= datetime.utcnow():
            raise ValueError("expired")
        result = await current_runtime_person(reference["user_id"])
        if result is None:
            raise ValueError("person unavailable")
        user, tenant = result
        if user.token_version != reference["token_version"] or tenant != reference["tenant_id"]:
            raise ValueError("identity changed")
    except (KeyError, TypeError, ValueError) as exc:
        raise PermissionDeniedError(reason="runtime_web_identity_invalid") from exc
    return await UserPayload.init_login_user(
        user_id=user.user_id, user_name=user.user_name, tenant_id=tenant, token_version=user.token_version
    )


async def resolve_preview_person(user_id):
    """Resolve current active membership and current privileges; no saved browser scope."""
    result = await current_runtime_person(user_id)
    if result is None:
        raise PermissionDeniedError(reason="preview_person_unavailable")
    user, tenant = result
    return await UserPayload.init_login_user(
        user_id=user.user_id, user_name=user.user_name, tenant_id=tenant, token_version=user.token_version
    )
