"""覆盖 AC: AC-18, AC-22, AC-29, AC-31."""

import asyncio
from contextlib import contextmanager

import pytest
from sqlalchemy import CheckConstraint
from sqlmodel import select

from bisheng.common.errcode.dsh import DshOperationConflictError
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.dsh.domain.models.model_audit_setting import DshModelAuditSetting
from bisheng.dsh.domain.repositories.model_audit_setting import DshModelAuditSettingRepository
from bisheng.dsh.domain.schemas.model_audit import AuditModeCommand
from bisheng.dsh.domain.services.model_audit_setting import DshModelAuditSettingService
from test.dsh.model_audit_fixtures import AUDIT_MODELS, audit_database, audit_session


def test_tables_have_tenant_and_lifecycle_without_plaintext():
    for model in AUDIT_MODELS:
        columns = model.__table__.c
        assert {"tenant_id", "create_time", "update_time"} <= set(columns.keys())
        assert columns.tenant_id.index
        assert not {"messages", "input_body", "output_body", "prompt", "response"} & set(columns.keys())
    assert any(isinstance(c, CheckConstraint) for c in DshModelAuditSetting.__table__.constraints)


def test_mode_and_change_history_rollback_together():
    from bisheng.dsh.domain.models.model_audit_setting import DshModelAuditSettingChange

    with audit_database() as engine:
        with audit_session(engine) as session:
            DshModelAuditSettingRepository(session).change(
                AuditModeCommand(operation_id="rollback", expected_version=0, mode="CONTENT"),
                actor_user_id=20,
            )
            session.rollback()
        with audit_session(engine) as session:
            assert DshModelAuditSettingRepository(session).read().mode == "OFF"
            assert list(session.exec(select(DshModelAuditSettingChange))) == []


def test_off_default_atomic_changes_idempotency_and_tenant_isolation():
    with audit_database() as engine:
        with audit_session(engine) as session:
            repo = DshModelAuditSettingRepository(session)
            assert repo.read().mode == "OFF"
            cmd = AuditModeCommand(operation_id="operation-1", expected_version=0, mode="CONTENT")
            changed = repo.change(cmd, actor_user_id=20)
            session.commit()
            assert changed.version == 1 and changed.mode == "CONTENT"
            assert repo.change(cmd, actor_user_id=20) == changed
            with pytest.raises(DshOperationConflictError):
                repo.change(cmd.model_copy(update={"mode": "OFF"}), actor_user_id=20)
            with pytest.raises(DshOperationConflictError):
                repo.change(cmd.model_copy(update={"operation_id": "operation-2"}), actor_user_id=20)
        with audit_session(engine, 3) as session:
            assert DshModelAuditSettingRepository(session).read().mode == "OFF"
            assert list(session.exec(select(DshModelAuditSetting))) == []


async def test_failed_and_timed_out_mode_reads_are_off_without_stale_cache():
    async def fail():
        raise OSError("synthetic unavailable")

    service = DshModelAuditSettingService(fail, timeout_seconds=0.01)
    assert (await service.read_effective()).mode == "OFF"
    assert (await service.read_effective()).read_failed

    async def wait():
        await asyncio.sleep(1)

    service = DshModelAuditSettingService(wait, timeout_seconds=0.01)
    assert (await service.read_effective()).mode == "OFF"


async def test_returned_mode_snapshot_is_independent_of_later_changes():
    from bisheng.dsh.domain.schemas.model_audit import AuditModeSnapshot

    current = ["CONTENT"]

    async def read():
        return AuditModeSnapshot(mode=current[0])

    service = DshModelAuditSettingService(read, timeout_seconds=0.01)
    first = await service.read_effective()
    current[0] = "OFF"
    assert first.mode == "CONTENT"
    assert (await service.read_effective()).mode == "OFF"


async def test_admin_reader_reuses_scope_and_only_instance_admin_can_write():
    calls = []

    async def authorize(actor_id, tenant_id):
        calls.append((actor_id, tenant_id))
        if actor_id == 20 and tenant_id != 2:
            raise PermissionDeniedError()
        return {"scope": "instance" if actor_id == 1 else "tenant", "tenant_id": "2"}, tenant_id

    with audit_database() as engine:

        @contextmanager
        def repositories():
            from sqlmodel import Session

            with Session(engine, expire_on_commit=False) as session:
                yield DshModelAuditSettingRepository(session)
                session.commit()

        service = DshModelAuditSettingService(
            None, timeout_seconds=0.01, authorize_admin=authorize, repository_scope=repositories
        )
        assert (await service.read_admin(20, 2)).mode == "OFF"
        command = AuditModeCommand(operation_id="super-operation", expected_version=0, mode="METADATA")
        with pytest.raises(PermissionDeniedError):
            await service.change_admin(20, 2, command)
        with pytest.raises(PermissionDeniedError):
            await service.read_admin(20, 3)
        assert (await service.change_admin(1, 2, command)).mode == "METADATA"
        assert (await service.read_admin(20, 2)).mode == "METADATA"
    assert (20, 3) in calls
