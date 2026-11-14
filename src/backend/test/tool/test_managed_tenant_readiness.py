"""Pending resource data fails before the global-super permission shortcut."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.flow import WorkflowCreationPendingError
from bisheng.common.errcode.knowledge import KnowledgeCPError
from bisheng.common.errcode.tool import ToolCreationPendingError
from bisheng.core.context.tenant import bypass_tenant_filter, tenant_execution_scope
from bisheng.database.models.flow import Flow
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.permission.application.business_authorization import batch_check_business_actions, check_business_action
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from bisheng.tool.domain.models.gpts_tools import GptsToolsType
from test.fixtures.managed_tenant import managed_db as managed_db


@pytest.mark.parametrize(
    "kind,error",
    [
        ("tool", ToolCreationPendingError),
        ("workflow", WorkflowCreationPendingError),
        ("knowledge_library", KnowledgeCPError),
    ],
)
async def test_global_super_cannot_consume_pending_parent(managed_db, monkeypatch, kind, error):
    import bisheng.permission.application.business_authorization as actions
    from bisheng.knowledge.domain.repositories import copy_repository as copies
    from bisheng.tool.domain.repositories import creation_repository as tools
    from bisheng.workflow.domain.repositories import creation_repository as flows

    await managed_db.create(GptsToolsType, Flow, Knowledge)
    for module in (tools, flows, copies):
        monkeypatch.setattr(module, "get_async_db_session", managed_db.sessions)
    with bypass_tenant_filter():
        async with managed_db.sessions() as session:
            session.add_all(
                [
                    GptsToolsType(id=9, name="pending", tenant_id=2, user_id=7, creation_state="PENDING"),
                    Flow(id="9", name="pending", tenant_id=2, user_id=7, flow_type=10, creation_state="PENDING"),
                    Knowledge(id=9, name="copy", tenant_id=2, user_id=7, copy_source_id=8, state=0),
                ]
            )
            await session.commit()
    monkeypatch.setattr(
        actions,
        "resolve_permission_actor",
        AsyncMock(return_value=PermissionActor(user_id=7, tenant_id=1, super_admin=True)),
    )
    with tenant_execution_scope(1), pytest.raises(error):
        await check_business_action(SimpleNamespace(), resource_type=kind, resource_id="9", action="use")
    with tenant_execution_scope(1), pytest.raises(error):
        await batch_check_business_actions(SimpleNamespace(), resource_type=kind, resource_ids=["9"], actions=["use"])
