import asyncio
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


async def test_management_detail_projects_summary_and_checks_edit_before_returning_graph(monkeypatch):
    from bisheng.api.services import flow as service
    from bisheng.common.errcode.http_error import UnAuthorizedError
    from bisheng.common.schemas.api import resp_200
    from bisheng.core.context.tenant import get_current_tenant_id, is_strict_tenant_filter

    async def read_flow(_user, _flow_id):
        assert get_current_tenant_id() == 7 and is_strict_tenant_filter()
        return resp_200({"id": "flow", "name": "Visible", "status": 1, "data": {"nodes": []}})

    monkeypatch.setattr(service.FlowService, "get_one_flow", read_flow)
    monkeypatch.setattr(
        service.FlowService,
        "get_version_list_by_flow",
        AsyncMock(return_value=resp_200({"data": [], "total": 0})),
    )
    authorize = AsyncMock(side_effect=[UnAuthorizedError(), None])
    monkeypatch.setattr(service, "require_business_action", authorize)
    user = SimpleNamespace(user_id=11, tenant_id=7)
    summary = await service.FlowService.get_management_flow(user, "flow")
    assert summary.data["name"] == "Visible"
    assert "data" not in summary.data
    with pytest.raises(UnAuthorizedError):
        await service.FlowService.get_management_flow(user, "flow", for_edit=True)
    graph = await service.FlowService.get_management_flow(user, "flow", for_edit=True)
    assert graph.data["data"] == {"nodes": []}
    assert authorize.await_args.kwargs["action"] == "edit"


async def test_management_creation_retries_without_enrolling_workflow(registration_store, monkeypatch):
    from bisheng.workflow.application import kunlian_workflow_management as management
    from bisheng.workflow.application.kunlian_workflow_creation import create_registered_workflow
    from bisheng.workflow.domain.schemas.kunlian_registration import RegistrationScope

    repo = registration_store
    user = SimpleNamespace(user_id=11, tenant_id=7)
    quota = AsyncMock()
    project = AsyncMock(side_effect=[RuntimeError("projection failed"), None])
    args = (repo, user, FlowCreate(name="management"), "request-key", quota, project)
    with pytest.raises(WorkflowRegistrationPending):
        await create_registered_workflow(*args, workflow_management=True)
    pending_id = project.await_args.args[0].id
    assert repo.pending_ids(7, [pending_id]) == {pending_id}
    with pytest.raises(WorkflowRegistrationPending):
        management.workflow_scope(7, pending_id, user=user, repository=repo)
    flow, version = await create_registered_workflow(*args, workflow_management=True)
    repeated, repeated_version = await create_registered_workflow(*args, workflow_management=True)
    assert repeated.id == flow.id == pending_id and version == repeated_version
    quota.assert_awaited_once()
    monkeypatch.setattr(management, "mock_scope", lambda _: RegistrationScope(7, "mock", 1))
    assert management.workflow_scope(7, flow.id, user=user, repository=repo) is None


async def test_management_concurrent_submissions_reuse_workflow_and_initial_version(registration_store):
    from bisheng.workflow.application.kunlian_workflow_creation import create_registered_workflow

    checked = asyncio.Event()
    arrivals = 0

    async def check_quota():
        nonlocal arrivals
        arrivals += 1
        if arrivals == 2:
            checked.set()
        await asyncio.wait_for(checked.wait(), timeout=5)

    user = SimpleNamespace(user_id=11, tenant_id=7)
    args = (registration_store, user, FlowCreate(name="concurrent"), "same-key", check_quota, AsyncMock())
    first, second = await asyncio.gather(
        create_registered_workflow(*args, workflow_management=True),
        create_registered_workflow(*args, workflow_management=True),
    )
    assert (first[0].id, first[1]) == (second[0].id, second[1])
    with pytest.raises(WorkflowRegistrationConflict):
        await create_registered_workflow(
            registration_store,
            user,
            FlowCreate(name="different"),
            "same-key",
            AsyncMock(),
            AsyncMock(),
            workflow_management=True,
        )


async def test_management_retry_recovers_when_concurrent_create_consumes_last_quota(registration_store):
    from bisheng.common.errcode.tenant_quota import TenantRoleQuotaExceededError
    from bisheng.workflow.application.kunlian_workflow_creation import create_registered_workflow

    waiting = asyncio.Event()
    created = asyncio.Event()
    user = SimpleNamespace(user_id=11, tenant_id=7)
    request = FlowCreate(name="last slot")

    async def delayed_quota_check():
        waiting.set()
        await asyncio.wait_for(created.wait(), timeout=5)
        raise TenantRoleQuotaExceededError()

    duplicate = asyncio.create_task(
        create_registered_workflow(
            registration_store, user, request, "last-key", delayed_quota_check, AsyncMock(), workflow_management=True
        )
    )
    await asyncio.wait_for(waiting.wait(), timeout=5)
    flow, version = await create_registered_workflow(
        registration_store, user, request, "last-key", AsyncMock(), AsyncMock(), workflow_management=True
    )
    created.set()
    recovered, recovered_version = await duplicate
    assert (recovered.id, recovered_version) == (flow.id, version)
    with pytest.raises(TenantRoleQuotaExceededError):
        await create_registered_workflow(
            registration_store,
            user,
            FlowCreate(name="another"),
            "other-key",
            delayed_quota_check,
            AsyncMock(),
            workflow_management=True,
        )
