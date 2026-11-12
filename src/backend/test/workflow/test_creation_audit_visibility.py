"""Creation audit must see the committed workflow through its separate connection."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import Request
from sqlmodel import select

from bisheng.api.services import flow as service
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.database.models import audit_log, flow, org_snapshot
from bisheng.database.models.audit_log import AuditLog, EventType, ObjectType
from bisheng.database.models.flow import Flow, FlowCreate
from bisheng.database.models.flow_version import FlowVersion
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from bisheng.workflow.domain.repositories import creation_repository
from test.fixtures.managed_tenant import managed_db as managed_db
from test.fixtures.managed_tenant import management_scope


@pytest.mark.parametrize("target_tenant", [1, 2])
async def test_creation_audit_reads_committed_workflow(managed_db, monkeypatch, target_tenant):
    await managed_db.create(Flow, FlowVersion, AuditLog)
    monkeypatch.setattr(service, "get_async_db_session", managed_db.sessions)
    monkeypatch.setattr(creation_repository, "get_async_db_session", managed_db.sessions)
    monkeypatch.setattr(flow, "get_sync_db_session", managed_db.sync_sessions)
    monkeypatch.setattr(audit_log, "get_sync_db_session", managed_db.sync_sessions)
    monkeypatch.setattr("bisheng.api.services.audit_log.UserGroupDao.get_user_group", Mock(return_value=[]))
    monkeypatch.setattr(org_snapshot, "resolve_user_dept", Mock(return_value=(-1, None)))
    prepared = SimpleNamespace(verified=SimpleNamespace(references=()))
    runtime = SimpleNamespace(
        aprepare_source_bindings=AsyncMock(return_value=prepared),
        aapply_source_bindings=AsyncMock(),
    )
    monkeypatch.setattr(service, "get_reference_binding_runtime", AsyncMock(return_value=runtime))
    monkeypatch.setattr(
        service, "get_f048_resource_adapter", AsyncMock(return_value=SimpleNamespace(authorize_created=AsyncMock()))
    )
    monkeypatch.setattr(
        service, "resolve_permission_actor", AsyncMock(return_value=PermissionActor(user_id=7, tenant_id=target_tenant))
    )
    monkeypatch.setattr(service.FlowService, "get_logo_share_link", Mock())
    monkeypatch.setattr(service.telemetry_service, "log_event", AsyncMock())
    request = Request({"type": "http", "headers": [], "client": ("127.0.0.1", 12345)})
    user = SimpleNamespace(user_id=7, user_name="creator")
    payload = FlowCreate(name="Audit visibility regression", data={"nodes": [], "edges": []})

    # Keep the actual creation service, repositories, audit lookup and audit insert.
    # Mocking create_build_workflow would conceal the separate-connection failure.
    with management_scope(1, target_tenant):
        result = await service.FlowService.create_workflow(request, user, payload)

    assert result.status_code == 200
    with bypass_tenant_filter(), managed_db.sync_sessions() as session:
        root = session.exec(select(Flow)).one()
        version = session.exec(select(FlowVersion)).one()
        audit = session.exec(select(AuditLog)).one()
        assert root.id == version.flow_id == audit.object_id == result.data.id
        assert root.tenant_id == version.tenant_id == audit.tenant_id == target_tenant
        assert root.creation_state == "READY"
        assert result.data.version_id == version.id
        assert audit.object_name == "Audit visibility regression"
        assert audit.event_type == EventType.CREATE_BUILD.value
        assert audit.object_type == ObjectType.WORK_FLOW.value
        assert audit.operator_id == 7
