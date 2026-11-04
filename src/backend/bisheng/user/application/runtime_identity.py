"""Current verified identity value for server-owned delayed web work."""

from datetime import UTC, datetime

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.common.services.config_service import settings
from bisheng.user.domain.repositories.runtime_identity import current_person_rows, current_runtime_person


async def read_current_person_facts(user_ids):
    """Current identity facts, never the request actor or a synthetic session."""
    ids = tuple(dict.fromkeys(int(value) for value in user_ids if str(value).isdigit() and int(value) > 0))
    grouped = {ident: [] for ident in ids}
    for user, tenant in await current_person_rows(ids):
        if user.user_id in grouped:
            grouped[user.user_id].append((user, tenant))
    result = {}
    for ident, rows in grouped.items():
        user = rows[0][0] if rows else None
        tenants = {tenant for _, tenant in rows if tenant is not None}
        if user is None or user.delete != 0:
            state, tenant = "inactive", None
        elif not settings.multi_tenant.enabled:
            state, tenant = "active", 1
        elif len(tenants) == 1:
            state, tenant = "active", next(iter(tenants))
        else:
            state, tenant = ("ambiguous" if len(tenants) > 1 else "inactive"), None
        result[ident] = {
            "id": ident,
            "name": user.user_name if user else None,
            "state": state,
            "tenant_id": tenant,
            "token_version": user.token_version if user else None,
        }
    return result


async def resolve_web_creation_identity(reference):
    try:
        expires = datetime.fromisoformat(reference["expires_at"])
        expires = expires.replace(tzinfo=UTC) if expires.tzinfo is None else expires
        if reference["kind"] != "web_session" or expires <= datetime.now(UTC):
            raise ValueError("expired")
        facts = (await read_current_person_facts([reference["user_id"]]))[reference["user_id"]]
        if facts["state"] == "active" and facts["tenant_id"] != reference["tenant_id"]:
            raise PermissionDeniedError(reason="web_creation_tenant_changed")
        if (
            facts["state"] != "active"
            or facts["tenant_id"] != reference["tenant_id"]
            or facts["token_version"] != reference["token_version"]
        ):
            raise ValueError("identity changed")
    except (KeyError, TypeError, ValueError) as exc:
        raise PermissionDeniedError(reason="web_creation_identity_invalid") from exc
    return await UserPayload.init_login_user(
        user_id=facts["id"], user_name=facts["name"], tenant_id=facts["tenant_id"], token_version=facts["token_version"]
    )


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
