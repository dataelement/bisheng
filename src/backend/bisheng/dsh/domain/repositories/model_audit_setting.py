"""Tenant-mode transactions with atomic, idempotent change history."""

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from bisheng.common.errcode.dsh import DshOperationConflictError
from bisheng.common.errcode.dsh_audit import DshAuditEncryptionUnavailableError
from bisheng.core.context.tenant import strict_tenant_filter
from bisheng.dsh.domain.models.model_audit_setting import DshModelAuditSetting, DshModelAuditSettingChange
from bisheng.dsh.domain.repositories.admin_operation import require_tenant
from bisheng.dsh.domain.schemas.model_audit import AuditModeCommand, AuditModeSnapshot


class DshModelAuditSettingRepository:
    def __init__(self, session: Session):
        self.session = session

    def _row(self, *, lock=False):
        require_tenant()
        statement = select(DshModelAuditSetting)
        if lock:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        with strict_tenant_filter():
            return self.session.exec(statement).one_or_none()

    def read(self) -> AuditModeSnapshot:
        row = self._row()
        return AuditModeSnapshot(mode=row.mode, version=row.version) if row else AuditModeSnapshot()

    def change(
        self, command: AuditModeCommand, *, actor_user_id: int, content_available: bool = False
    ) -> AuditModeSnapshot:
        require_tenant()
        with strict_tenant_filter():
            previous = self.session.exec(
                select(DshModelAuditSettingChange).where(
                    DshModelAuditSettingChange.operation_id == command.operation_id
                )
            ).one_or_none()
        if previous:
            if (previous.actor_user_id, previous.expected_version, previous.after_mode) != (
                actor_user_id,
                command.expected_version,
                command.mode,
            ):
                raise DshOperationConflictError()
            return AuditModeSnapshot(mode=previous.after_mode, version=previous.result_version)
        row = self._row(lock=True)
        before = row.mode if row else "OFF"
        version = row.version if row else 0
        if version != command.expected_version:
            raise DshOperationConflictError()
        if command.mode == "CONTENT" and not content_available:
            raise DshAuditEncryptionUnavailableError()
        try:
            with self.session.begin_nested():
                if row is None:
                    row = DshModelAuditSetting()
                row.mode, row.version, row.updated_by = command.mode, version + 1, actor_user_id
                self.session.add(row)
                self.session.add(
                    DshModelAuditSettingChange(
                        operation_id=command.operation_id,
                        actor_user_id=actor_user_id,
                        before_mode=before,
                        after_mode=command.mode,
                        expected_version=version,
                        result_version=version + 1,
                    )
                )
                self.session.flush()
        except IntegrityError:
            raise DshOperationConflictError() from None
        return AuditModeSnapshot(mode=row.mode, version=row.version)
