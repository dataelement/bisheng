"""Assistant creation audit reads the committed row through a separate connection."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import Request
from sqlmodel import select

from bisheng.api.services import assistant as service
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.database.models import assistant, audit_log, org_snapshot
from bisheng.database.models.assistant import Assistant
from bisheng.database.models.audit_log import AuditLog, EventType, ObjectType
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from test.fixtures.managed_tenant import managed_db as managed_db
from test.fixtures.managed_tenant import management_scope


@pytest.mark.parametrize("target_tenant", [1, 2])
@pytest.mark.parametrize("projection_fails", [False, True])
async def test_creation_audit_observes_only_committed_assistants(
    managed_db, monkeypatch, target_tenant, projection_fails
):
    await managed_db.create(Assistant, AuditLog)
    monkeypatch.setattr(service, "get_async_db_session", managed_db.sessions)
    monkeypatch.setattr(assistant, "get_sync_db_session", managed_db.sync_sessions)
    monkeypatch.setattr(audit_log, "get_sync_db_session", managed_db.sync_sessions)
    monkeypatch.setattr(service.AssistantService, "judge_name_repeat", Mock(return_value=False))
    monkeypatch.setattr(service.AssistantService, "get_logo_share_link", Mock())
    monkeypatch.setattr(service.LLMService, "get_assistant_llm", AsyncMock(return_value=SimpleNamespace(llm_list=[])))
    monkeypatch.setattr(service, "check_business_action", AsyncMock(return_value=False))
    monkeypatch.setattr(service.telemetry_service, "log_event", AsyncMock())
    monkeypatch.setattr("bisheng.api.services.audit_log.UserGroupDao.get_user_group", Mock(return_value=[]))
    monkeypatch.setattr(org_snapshot, "resolve_user_dept", Mock(return_value=(-1, None)))
    runtime = SimpleNamespace(aprepare_source_bindings=AsyncMock(), aapply_source_bindings=AsyncMock())
    monkeypatch.setattr(service, "get_reference_binding_runtime", AsyncMock(return_value=runtime))
    authorize = AsyncMock(side_effect=RuntimeError("projection failed") if projection_fails else None)
    monkeypatch.setattr(
        service, "get_f048_resource_adapter", AsyncMock(return_value=SimpleNamespace(authorize_created=authorize))
    )
    monkeypatch.setattr(
        service, "resolve_permission_actor", AsyncMock(return_value=PermissionActor(user_id=7, tenant_id=target_tenant))
    )
    request = Request({"type": "http", "headers": [], "client": ("127.0.0.1", 12345)})
    user = SimpleNamespace(user_id=7, user_name="creator")
    new_assistant = Assistant(id="audit-creation", name="Assistant audit regression", user_id=7)

    # Exercise the real permission hook, insertion, audit lookup and audit write.
    with management_scope(1, target_tenant):
        if projection_fails:
            with pytest.raises(RuntimeError, match="projection failed"):
                await service.AssistantService.create_assistant(request, user, new_assistant)
        else:
            result = await service.AssistantService.create_assistant(request, user, new_assistant)
            assert result.id == "audit-creation"

    with bypass_tenant_filter(), managed_db.sync_sessions() as session:
        assistants = session.exec(select(Assistant)).all()
        audits = session.exec(select(AuditLog)).all()
        if projection_fails:
            assert assistants == [] and audits == []
        else:
            assert len(assistants) == len(audits) == 1
            root, audit = assistants[0], audits[0]
            assert root.id == audit.object_id == "audit-creation"
            assert root.tenant_id == audit.tenant_id == target_tenant
            assert audit.object_name == "Assistant audit regression"
            assert audit.event_type == EventType.CREATE_BUILD.value
            assert audit.object_type == ObjectType.ASSISTANT.value
