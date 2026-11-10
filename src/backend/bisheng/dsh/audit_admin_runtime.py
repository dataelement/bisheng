"""Audit administration uses existing identity/scope authorization, no Gateway writes."""

from dataclasses import dataclass

from bisheng.dsh.admin_runtime import authorize_admin
from bisheng.dsh.domain.repositories.model_audit_queries import DshModelAuditQueryRepository
from bisheng.dsh.domain.repositories.model_audit_setting import DshModelAuditSettingRepository
from bisheng.dsh.domain.services.model_audit_body_access import DshModelAuditBodyAccessService
from bisheng.dsh.domain.services.model_audit_queries import DshModelAuditQueryService
from bisheng.dsh.domain.services.model_audit_setting import DshModelAuditSettingService
from bisheng.dsh.infrastructure.model_audit_activity import shared_audit_activity
from bisheng.dsh.infrastructure.model_audit_keys import AuditKeyRing
from bisheng.dsh.infrastructure.model_audit_storage import BishengMinioAuditObjects, EncryptedAuditStorage
from bisheng.dsh.operations_runtime import repository_scope


@dataclass
class ModelAuditAdministration:
    queries: DshModelAuditQueryService
    bodies: DshModelAuditBodyAccessService
    modes: DshModelAuditSettingService


def build_audit_administration(settings):
    queries = DshModelAuditQueryService(
        authorize_admin,
        lambda: repository_scope(DshModelAuditQueryRepository),
        activity=shared_audit_activity,
        window=settings.audit_observation_window_seconds,
    )

    def storage():
        return EncryptedAuditStorage(
            BishengMinioAuditObjects(),
            AuditKeyRing.from_environment(active_id=settings.audit_active_key_id),
            max_block_bytes=settings.audit_chunk_bytes,
            timeout_seconds=settings.audit_store_timeout_seconds,
        )

    def content_readiness():
        AuditKeyRing.from_environment(active_id=settings.audit_active_key_id).resolve(settings.audit_active_key_id)
        return True

    modes = DshModelAuditSettingService(
        None,
        timeout_seconds=settings.audit_mode_read_timeout_seconds,
        authorize_admin=authorize_admin,
        repository_scope=lambda: repository_scope(DshModelAuditSettingRepository),
        content_readiness=content_readiness,
    )
    return ModelAuditAdministration(queries, DshModelAuditBodyAccessService(queries, storage), modes)
