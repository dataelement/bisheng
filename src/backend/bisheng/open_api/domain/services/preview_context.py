"""Preview capability ownership port; no caller-supplied owner, version or purpose."""

import time

from bisheng.common.errcode.open_api import OpenApiCredentialInvalidError

_provider = None


def register_preview_provider(provider):
    global _provider
    _provider = provider


async def resolve_preview_context(**reference):
    if _provider is None:
        raise OpenApiCredentialInvalidError()
    try:
        return await _provider.resolve(**reference)
    except Exception as exc:
        raise OpenApiCredentialInvalidError() from exc


async def bind_preview_principal(principal, verified):
    context = await resolve_preview_context(credential_id=principal.credential_id)
    if context is None:
        if getattr(verified, "preview_session", None):
            raise OpenApiCredentialInvalidError()
        return principal
    if (
        verified is None
        or (context.tenant_id, context.app_id, context.credential_id, context.viewer_user_id, context.session_id)
        != (
            principal.tenant_id,
            principal.subject_ref,
            principal.credential_id,
            verified.user_id,
            getattr(verified, "preview_session", None),
        )
        or not getattr(verified, "expires_at", None)
        or verified.expires_at <= time.time()
    ):
        raise OpenApiCredentialInvalidError()
    return principal.model_copy(
        update={
            "preview_session_id": context.session_id,
            "preview_version_id": context.version_id,
            "preview_purpose": context.purpose,
            "preview_viewer_user_id": context.viewer_user_id,
            "preview_capability_user_id": context.capability_user_id,
            "preview_obo_expires_at": verified.expires_at,
        }
    )


async def revalidate_preview(principal):
    context = await resolve_preview_context(credential_id=principal.credential_id)
    if not principal.preview_session_id:
        if context is not None:
            raise OpenApiCredentialInvalidError()
        return None
    if (
        context is None
        or (
            context.tenant_id,
            context.app_id,
            context.session_id,
            context.version_id,
            context.viewer_user_id,
            context.capability_user_id,
            context.purpose,
        )
        != (
            principal.tenant_id,
            principal.subject_ref,
            principal.preview_session_id,
            principal.preview_version_id,
            principal.preview_viewer_user_id,
            principal.preview_capability_user_id,
            principal.preview_purpose,
        )
        or not principal.preview_obo_expires_at
        or principal.preview_obo_expires_at <= time.time()
    ):
        raise OpenApiCredentialInvalidError()
    return context
