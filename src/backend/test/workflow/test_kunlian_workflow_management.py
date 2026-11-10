from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.flow import WorkflowRegistrationConflict, WorkflowRegistrationPending
from bisheng.database.models.flow import Flow, FlowCreate
from bisheng.database.models.flow_version import FlowVersion


@pytest.mark.asyncio
async def test_creation_recovers_original_workflow_without_checking_quota_twice(registration_store):
    from bisheng.workflow.application.kunlian_workflow_creation import create_registered_workflow

    user = SimpleNamespace(user_id=11, tenant_id=7)
    flow = FlowCreate(name="test", user_id=99, status=2)
    quota = AsyncMock()
    project = AsyncMock(side_effect=[RuntimeError("projection failed"), None])
    args = registration_store, user, flow, "retry-key", quota, project
    with pytest.raises(WorkflowRegistrationPending):
        await create_registered_workflow(*args)
    first = project.await_args.args[0]
    finished, version_id = await create_registered_workflow(*args)
    repeated, repeated_version_id = await create_registered_workflow(*args)
    assert first.id == finished.id == repeated.id
    assert version_id == repeated_version_id
    assert finished.user_id == 11 and finished.tenant_id == 7 and finished.status == 1
    quota.assert_awaited_once()
    assert project.await_count == 2
    with pytest.raises(WorkflowRegistrationConflict):
        await create_registered_workflow(
            registration_store, user, FlowCreate(name="other"), "retry-key", quota, project
        )


def test_conditional_save_refuses_stale_revision(registration_store):
    from bisheng.workflow.application.kunlian_workflow_management import version_revision
    from bisheng.workflow.domain.schemas.kunlian_registration import RegistrationScope

    repo = registration_store
    flow = Flow(id="f" * 32, name="test", user_id=11, tenant_id=7)
    with repo.transaction() as session:
        session.add(flow)
        session.add(FlowVersion(id=1, flow_id=flow.id, name="v0", tenant_id=7, is_current=1))
        session.flush()
        initial = version_revision(session.get(FlowVersion, 1))
    scope = RegistrationScope(7, "mock", 1)
    saved = repo.save_draft(scope, flow.id, 1, initial, name="v1")
    assert saved["draft_revision"] != initial
    with pytest.raises(WorkflowRegistrationConflict):
        repo.save_draft(scope, flow.id, 1, initial, name="stale")
