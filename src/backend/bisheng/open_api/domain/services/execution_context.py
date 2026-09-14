"""Restore an immutable Open API identity at a background-worker boundary."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime

from bisheng.common.errcode.open_api import OpenApiCredentialInvalidError, PersonalTokenHolderInvalidError
from bisheng.common.services.config_service import settings
from bisheng.core.context.tenant import DEFAULT_TENANT_ID, current_tenant_id, visible_tenant_ids
from bisheng.open_api.domain.context import OpenApiExecutionSnapshot
from bisheng.open_api.domain.models.api_credential import (
    SUBJECT_KIND_NATURAL_PERSON,
    SUBJECT_KIND_SERVICE_ACCOUNT,
)
from bisheng.open_api.domain.repositories.credential_repository import CredentialRepository
from bisheng.open_api.domain.repositories.service_account_repository import ServiceAccountRepository
from bisheng.open_api.domain.services.tenant_setting_service import TenantSettingService
from bisheng.permission.application.data_scope import DATA_SCOPE_ALL
from bisheng.permission.application.identity import (
    reset_current_permission_actor,
    set_current_permission_actor,
)
from bisheng.permission.domain.services.permission_action_service import PermissionActor


def validate_execution_snapshot(snapshot: OpenApiExecutionSnapshot) -> None:
    if snapshot.channel == "public_v3":
        if snapshot.credential_id is not None:
            raise OpenApiCredentialInvalidError()
        return
    if snapshot.credential_id is None:
        raise OpenApiCredentialInvalidError()
    credential = CredentialRepository.get_for_execution_sync(snapshot.credential_id)
    if (
        credential is None
        or not credential.is_valid_at(datetime.now())
        or credential.tenant_id != snapshot.tenant_id
        or credential.subject_kind != snapshot.actor_kind
        or credential.subject_id != snapshot.actor_id
    ):
        raise OpenApiCredentialInvalidError()
    if credential.subject_kind == SUBJECT_KIND_SERVICE_ACCOUNT:
        account = ServiceAccountRepository.get_for_execution_sync(credential.subject_id)
        if account is None or not account.is_enabled or account.tenant_id != snapshot.tenant_id:
            raise OpenApiCredentialInvalidError()
    elif credential.subject_kind == SUBJECT_KIND_NATURAL_PERSON:
        if not settings.open_api.pat_enabled or not TenantSettingService.get_policy_sync(snapshot.tenant_id).enabled:
            raise OpenApiCredentialInvalidError()
        from sqlmodel import select

        from bisheng.core.context.tenant import bypass_tenant_filter
        from bisheng.core.database import get_sync_db_session
        from bisheng.database.models.tenant import UserTenant
        from bisheng.user.domain.models.user import User

        with bypass_tenant_filter(), get_sync_db_session() as session:
            user = session.exec(select(User).where(User.user_id == snapshot.actor_id)).first()
            membership = session.exec(
                select(UserTenant).where(
                    UserTenant.user_id == snapshot.actor_id,
                    UserTenant.tenant_id == snapshot.tenant_id,
                    UserTenant.is_active == 1,
                    UserTenant.status == "active",
                )
            ).first()
        if user is None or user.delete != 0 or membership is None:
            raise PersonalTokenHolderInvalidError()


@contextmanager
def restore_execution_context(snapshot_data: dict | None):
    if snapshot_data is None:
        yield None
        return
    snapshot = OpenApiExecutionSnapshot.model_validate(snapshot_data)
    validate_execution_snapshot(snapshot)
    data_scope = DATA_SCOPE_ALL
    if snapshot.channel == "open_api_v2" and snapshot.actor_kind == SUBJECT_KIND_NATURAL_PERSON:
        # F066: re-read at execution time — a narrowing applied after enqueue
        # must bind the queued task too (immediate-effect semantics), so the
        # snapshot never carries a stale scope.
        # The narrowing is a PAT policy, applied only by the v2 gate. A public
        # v3 snapshot is also a natural person (the default operator), but its
        # handshake resolves no narrowing; applying one here would let the
        # handshake admit a run that the Celery leg then rejects.
        data_scope = TenantSettingService.get_policy_sync(snapshot.tenant_id).data_scope
    tenant_token = current_tenant_id.set(snapshot.tenant_id)
    visible_token = visible_tenant_ids.set(frozenset({DEFAULT_TENANT_ID, snapshot.tenant_id}))
    # Service accounts never inherit privilege. ``PermissionActor`` already
    # force-clears both fields for them; gating here as well keeps that
    # invariant provable from this file instead of a distant constructor.
    is_user = snapshot.authorization_subject_type == "user"
    actor_token = set_current_permission_actor(
        PermissionActor(
            subject_type=snapshot.authorization_subject_type,
            subject_id=snapshot.authorization_subject_id,
            tenant_id=snapshot.tenant_id,
            super_admin=snapshot.super_admin and is_user,
            tenant_admin_tenant_ids=snapshot.tenant_admin_tenant_ids if is_user else frozenset(),
            data_scope=data_scope,
        )
    )
    try:
        yield snapshot
    finally:
        reset_current_permission_actor(actor_token)
        visible_tenant_ids.reset(visible_token)
        current_tenant_id.reset(tenant_token)


__all__ = ["restore_execution_context", "validate_execution_snapshot"]
