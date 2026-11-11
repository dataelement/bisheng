"""Flow/v0 use one frozen T and pending refuses exact normal lookup."""

from unittest.mock import Mock

import pytest
from sqlmodel import select

from bisheng.common.errcode.flow import WorkflowCreationPendingError
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.database.models.flow import Flow, FlowDao
from bisheng.database.models.flow_version import FlowVersion
from test.fixtures.managed_tenant import managed_db as managed_db
from test.fixtures.managed_tenant import management_scope


async def test_flow_version_and_parent_share_t(managed_db, monkeypatch):
    from bisheng.database.models import flow as module

    await managed_db.create(Flow, FlowVersion)
    monkeypatch.setattr(module, "get_sync_db_session", managed_db.sync_sessions)
    monkeypatch.setattr(module.telemetry_service, "log_event_sync", Mock())
    with management_scope(1, 2):
        parent = FlowDao.create_flow(Flow(name="A", tenant_id=2, user_id=7, flow_type=10, creation_state="PENDING"), 10)
        with pytest.raises(WorkflowCreationPendingError):
            FlowDao.get_flow_by_id(parent.id)
    with bypass_tenant_filter(), managed_db.sync_sessions() as session:
        version = session.exec(select(FlowVersion)).one()
        assert version.tenant_id == parent.tenant_id == 2


async def test_union_and_simple_read_hide_pending_but_keep_other_flow_types(managed_db, monkeypatch):
    from bisheng.database.models import flow as module
    from bisheng.database.models.assistant import Assistant

    await managed_db.create(Flow, Assistant, module.App)
    monkeypatch.setattr(module, "get_sync_db_session", managed_db.sync_sessions)
    monkeypatch.setattr(module, "get_async_db_session", managed_db.sessions)
    with bypass_tenant_filter():
        async with managed_db.sessions() as session:
            session.add_all(
                [
                    Flow(id="ready", name="ready", tenant_id=2, user_id=7, flow_type=10),
                    Flow(id="pending", name="pending", tenant_id=2, user_id=7, flow_type=10, creation_state="PENDING"),
                    Flow(id="other", name="other", tenant_id=2, user_id=7, flow_type=15, creation_state="PENDING"),
                ]
            )
            await session.commit()
    with management_scope(1, 2):
        data, _ = await FlowDao.aget_all_apps()
        assert {row["id"] for row in data} == {"ready", "other"}
        assert await FlowDao.get_one_flow_simple("pending") is None
        assert FlowDao.get_one_flow_simple_sync("other").id == "other"


@pytest.mark.parametrize("failure", [None, "permission", "audit"])
async def test_workflow_creation_permission_controls_readiness(managed_db, monkeypatch, failure):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from bisheng.api.services import flow as service
    from bisheng.permission.domain.services.permission_action_service import PermissionActor
    from bisheng.workflow.domain.repositories import creation_repository

    await managed_db.create(Flow)
    monkeypatch.setattr(creation_repository, "get_async_db_session", managed_db.sessions)
    with bypass_tenant_filter():
        async with managed_db.sessions() as session:
            row = Flow(id="creation", name="new", user_id=7, tenant_id=2, flow_type=10, creation_state="PENDING")
            session.add(row)
            await session.commit()
    authorize = AsyncMock(side_effect=RuntimeError("fixture permission failure") if failure == "permission" else None)
    monkeypatch.setattr(
        service, "get_f048_resource_adapter", AsyncMock(return_value=SimpleNamespace(authorize_created=authorize))
    )
    monkeypatch.setattr(
        service, "resolve_permission_actor", AsyncMock(return_value=PermissionActor(user_id=7, tenant_id=2))
    )
    monkeypatch.setattr(service, "get_request_ip", Mock(return_value="fixture"))
    monkeypatch.setattr(
        service.AuditLogService,
        "create_build_workflow",
        Mock(side_effect=RuntimeError("fixture audit failure") if failure == "audit" else None),
    )
    monkeypatch.setattr(service.FlowService, "get_logo_share_link", Mock())
    with management_scope(1, 2):
        if failure:
            with pytest.raises(WorkflowCreationPendingError if failure == "permission" else RuntimeError):
                await service.FlowService.complete_creation(SimpleNamespace(), SimpleNamespace(user_id=7), row)
        else:
            await service.FlowService.complete_creation(SimpleNamespace(), SimpleNamespace(user_id=7), row)
    with bypass_tenant_filter():
        async with managed_db.sessions() as session:
            assert (await session.get(Flow, "creation")).creation_state == (
                "PENDING" if failure == "permission" else "READY"
            )
    assert authorize.await_args.kwargs["record"].tenant_id == 2
