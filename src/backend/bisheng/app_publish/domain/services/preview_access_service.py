"""Current dual-purpose preview qualifications, independently of browser tenant state."""

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime

from bisheng.app_publish.domain.repositories.preview_runtime_repository import PreviewRuntimeRepository
from bisheng.app_runtime.application.authorization import authorize_app
from bisheng.approval.application.app_review import pending_app_reviews
from bisheng.common.errcode.app_factory import AppNotFoundError
from bisheng.common.errcode.app_publish import AppPreviewForbiddenError
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.core.context.tenant import management_tenant_scope, tenant_execution_scope
from bisheng.open_api.application.runtime_authorization import without_open_api_identity
from bisheng.open_api.application.runtime_credentials import preview_credential_is_live
from bisheng.permission.application.identity import reset_current_permission_actor, set_current_permission_actor
from bisheng.user.application.runtime_identity import resolve_preview_person


@dataclass(frozen=True)
class PreviewQualification:
    tenant_id: int
    app_id: str
    version_id: str
    viewer_user_id: int
    purpose: str
    approval_instance_id: int | None = None
    approval_task_id: int | None = None


@dataclass(frozen=True)
class CapabilityAccessContext:
    tenant_id: int
    app_id: str
    version_id: str
    purpose: str
    viewer_user_id: int
    capability_user_id: int
    session_id: str
    credential_id: int
    operation_id: str
    approval_instance_id: int | None
    approval_task_id: int | None


async def load_app(app_id):
    return await PreviewRuntimeRepository.read_application(app_id)


async def qualify(app_id, version_id, *, actor, purpose):
    user_id = int(getattr(actor, "user_id", 0) or 0)
    if user_id <= 0 or purpose not in {None, "management", "approval"}:
        raise AppPreviewForbiddenError(reason="preview_purpose_invalid")
    grants = [g for g in await pending_app_reviews(user_id, app_id, {version_id}) if g.version_id == version_id]
    management = False
    if purpose != "approval":
        try:
            await authorize_app(actor, app_id, "management_preview")
            management = True
        except (PermissionDeniedError, AppNotFoundError):
            pass
    if purpose is None:
        if management == bool(grants):
            raise AppPreviewForbiddenError(reason="preview_purpose_required")
        purpose = "management" if management else "approval"
    app = await load_app(app_id)
    if app is None or app.state == "deleted":
        raise AppPreviewForbiddenError(reason="preview_app_missing")
    if purpose == "management":
        if not management:
            raise AppPreviewForbiddenError(reason="preview_edit_required")
        return PreviewQualification(app.tenant_id, app.id, version_id, user_id, purpose)
    if len(grants) != 1 or grants[0].tenant_id != app.tenant_id:
        raise AppPreviewForbiddenError(reason="preview_pending_task_required")
    g = grants[0]
    return PreviewQualification(g.tenant_id, app.id, version_id, user_id, purpose, g.instance_id, g.task_id)


async def validate_binding(row, *, viewer_user_id=None, credential_id=None, allow_starting=False):
    if (
        row is None
        or row.status not in ({"starting", "running"} if allow_starting else {"running"})
        or row.expires_at <= datetime.utcnow()
        or row.purpose not in {"management", "approval"}
        or not row.credential_id
        or not row.operation_id
        or (viewer_user_id is not None and viewer_user_id != row.viewer_user_id)
        or (credential_id is not None and credential_id != row.credential_id)
    ):
        raise AppPreviewForbiddenError(reason="preview_binding_invalid")
    from bisheng.app_runtime.application.preview_operations import verify_preview_execution

    if not await verify_preview_execution(row) or not await preview_credential_is_live(
        row.credential_id, row.tenant_id, row.app_id
    ):
        raise AppPreviewForbiddenError(reason="preview_execution_or_identity_unavailable")
    app = await load_app(row.app_id)
    if app is None or app.state == "deleted" or app.tenant_id != row.tenant_id:
        raise AppPreviewForbiddenError(reason="preview_app_missing")
    with without_open_api_identity():
        token = set_current_permission_actor(None)
        try:
            actor = await resolve_preview_person(row.viewer_user_id)
            if actor.tenant_id != row.tenant_id and not bool(getattr(actor, "is_global_super", False)):
                raise AppPreviewForbiddenError(reason="preview_viewer_tenant_changed")
            with tenant_execution_scope(row.tenant_id), management_tenant_scope(row.tenant_id):
                if row.purpose == "management":
                    await authorize_app(actor, app.id, "management_preview")
                    ceiling = row.viewer_user_id
                else:
                    grants = await pending_app_reviews(row.viewer_user_id, app.id, {row.version_id})
                    if not any(
                        (g.tenant_id, g.version_id, g.instance_id, g.task_id)
                        == (row.tenant_id, row.version_id, row.approval_instance_id, row.approval_task_id)
                        for g in grants
                    ):
                        raise AppPreviewForbiddenError(reason="preview_pending_task_required")
                    ceiling = app.owner_user_id
        finally:
            reset_current_permission_actor(token)
    return CapabilityAccessContext(
        row.tenant_id,
        app.id,
        row.version_id,
        row.purpose,
        row.viewer_user_id,
        ceiling,
        row.session_id,
        row.credential_id,
        row.operation_id,
        row.approval_instance_id,
        row.approval_task_id,
    )


@asynccontextmanager
async def qualified_scope(app_id, version_id, *, actor, purpose):
    qualification = await qualify(app_id, version_id, actor=actor, purpose=purpose)
    with tenant_execution_scope(qualification.tenant_id):
        yield qualification
