"""Unified platform issuance and authoritative credential routing for Desktop SSO."""

import jwt

from bisheng.common.errcode.dsh import (
    ERROR_BY_CLIENT_CODE,
    DshAuthorizationUnavailableError,
    DshInvalidAccessTokenError,
    DshInvalidGrantError,
    DshUserDisabledError,
)
from bisheng.common.errcode.platform_auth import PlatformAuthError
from bisheng.user.platform_auth_runtime import get_platform_auth


def desktop_auth_error(exc):
    """Translate platform failures to the frozen Desktop protocol."""
    reason = {
        "access_expired": "session_expired",
        "legacy_web_token_rejected": "invalid_access_token",
        "web_bootstrap_required": "invalid_access_token",
    }.get(exc.reason, exc.reason)
    error = ERROR_BY_CLIENT_CODE.get(reason)
    if error is None:
        error = DshAuthorizationUnavailableError if exc.http_status == 503 else DshInvalidAccessTokenError
    return error()


async def platform_call(operation):
    """Preserve the frozen DSH HTTP error envelope without credential fallback."""
    try:
        return await operation
    except PlatformAuthError as exc:
        raise desktop_auth_error(exc) from exc


async def validate_desktop_session(runtime, principal):
    """Revalidate the authority that issued this Desktop identity, without fallback."""
    if principal.platform_reference is not None:
        await platform_call(runtime.platform_sessions.validate_reference(principal.platform_reference))
    else:
        await runtime.sessions.validate(principal)


async def issue_desktop_session(request, identity, binding):
    if not identity.active:
        raise DshUserDisabledError()
    if binding["client_id"] != "dsh-desktop":
        raise DshInvalidGrantError()
    data = await platform_call(
        get_platform_auth(request).issue(
            int(identity.user_id),
            int(identity.tenant_id),
            "bisheng-desktop",
            device_label=binding.get("device_name"),
            client_version=binding.get("client_version"),
        )
    )
    data["user"] = identity.user.model_dump()
    data["tenant"] = identity.tenant.model_dump()
    return data


async def owns_platform_refresh(service, credential):
    # These opaque tokens share a shape with legacy DSH. Only persisted ownership
    # selects a validator; revoked/expired/used platform rows still belong here.
    digest = service.digest(credential)
    return await service.run(lambda repo: repo.refresh(digest) is not None, read_only=True)


async def refresh_desktop_session(request, runtime, credential):
    service = get_platform_auth(request)
    if await platform_call(owns_platform_refresh(service, credential)):
        data = await platform_call(service.refresh(credential))
        profile = await runtime.identity.profile(str(data["tenant"]["id"]), str(data["user"]["id"]))
        data.update(profile)
        return data
    return await runtime.sessions.refresh(credential)


async def logout_desktop_session(request, runtime, *, credential, refresh=False):
    if refresh:
        service = get_platform_auth(request)
        if await platform_call(owns_platform_refresh(service, credential)):
            await platform_call(service.logout(credential, refresh=True))
        else:
            await runtime.sessions.logout_refresh(credential)
        return
    parts = credential.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise DshInvalidAccessTokenError()
    try:
        header = jwt.get_unverified_header(parts[1])
    except jwt.InvalidTokenError as exc:
        raise DshInvalidAccessTokenError() from exc
    # The untrusted header chooses exactly one validator, never authenticates it.
    if header.get("typ") == "bisheng-platform-access+jwt" or header.get("kid") == "platform-access-v1":
        await platform_call(get_platform_auth(request).logout(parts[1]))
        return
    principal = await runtime.access.decode(credential)
    await runtime.sessions.revoke(principal.tenant_id, principal.user_id, principal.session_id)
