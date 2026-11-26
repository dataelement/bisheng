"""Real published service/endpoint keep original principal and admit before writes. 覆盖 AC: AC-37, AC-68, AC-87, AC-91."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.database.models.flow import Flow
from bisheng.database.models.flow_version import FlowVersion
from bisheng.open_api.domain.context import OpenApiExecutionSnapshot
from bisheng.open_endpoints.api.endpoints import workflow as endpoint
from bisheng.open_endpoints.domain.schemas.workflow import OpenWorkflowInvokeRequest
from bisheng.workflow.application import execution_admission as facade
from bisheng.workflow.domain.services import published_workflow_service as module
from test.knowledge_unification import test_wf_entry as entry_fixtures
from test.open_api.test_dependencies import service_account_principal

store = entry_fixtures.store
tenant = entry_fixtures.tenant
admission = entry_fixtures.admission


@pytest.fixture
def published(monkeypatch):
    user = UserPayload(user_id=11, user_name="original", tenant_id=101, user_role=[])
    callback = Mock()
    callback.get_workflow_status.return_value = None
    monkeypatch.setattr(module, "RedisCallback", Mock(return_value=callback))
    monkeypatch.setattr(
        module.PublishedWorkflowService,
        "get_workflow",
        AsyncMock(return_value=SimpleNamespace(id="wf", name="wf", data={"nodes": [], "edges": []})),
    )
    monkeypatch.setattr(module.ChatSessionService, "get_subject_session_if_exists", AsyncMock(return_value=None))
    create = AsyncMock()
    monkeypatch.setattr(module.ChatSessionService, "create_subject_session", create)
    monkeypatch.setattr(module.workflow_stateful_worker, "find_task_node", AsyncMock(return_value="q"))
    queue = Mock()
    monkeypatch.setattr(module, "execute_workflow", queue)
    snapshot = OpenApiExecutionSnapshot.from_principal(service_account_principal(), trace_id="trace")
    return SimpleNamespace(
        user=user,
        callback=callback,
        create=create,
        queue=queue,
        kwargs={
            "workflow_id": "wf",
            "operator": user,
            "session_subject": object(),
            "execution_snapshot": snapshot,
            "session_id": None,
            "override": None,
            "user_input": None,
            "message_id": None,
        },
    )


async def test_admission_rejection_has_no_session_redis_or_enqueue_writes(published, monkeypatch):
    gate = AsyncMock(side_effect=ResourceReferenceInvalidError())
    monkeypatch.setattr(module, "prepare_saved", gate, raising=False)
    with pytest.raises(ResourceReferenceInvalidError):
        await module.PublishedWorkflowService.prepare_invocation(**published.kwargs)
    gate.assert_awaited_once_with(published.user, "wf", override=None)
    published.create.assert_not_awaited()
    published.callback.set_workflow_data.assert_not_called()
    published.callback.set_workflow_status.assert_not_called()
    published.queue.apply_async.assert_not_called()


async def test_only_admitted_graph_is_queued_and_override_is_not_applied_twice(published, monkeypatch):
    graph = {"nodes": [{"data": {"id": "approved"}}], "edges": []}
    gate = AsyncMock(return_value=SimpleNamespace(graph=graph))
    monkeypatch.setattr(module, "prepare_saved", gate, raising=False)
    published.kwargs["override"] = {"node": {"prompt": "safe"}}
    await module.PublishedWorkflowService.prepare_invocation(**published.kwargs)
    gate.assert_awaited_once_with(published.user, "wf", override=published.kwargs["override"])
    published.callback.set_workflow_data.assert_called_once_with(graph)
    published.queue.apply_async.assert_called_once()
    assert published.queue.apply_async.call_args.args[0][3] == published.user.user_id


async def seed_model_graph(context):
    graph = {
        "nodes": [
            {
                "data": {
                    "id": "llm",
                    "type": "llm",
                    "group_params": [
                        {"params": [{"key": "model_id", "value": 7}, {"key": "prompt", "value": "original"}]}
                    ],
                }
            }
        ],
        "edges": [],
    }
    async with AsyncSession(context.engine) as session, session.begin():
        await session.execute(sa.update(Flow).where(Flow.id == "wf", Flow.tenant_id == 101).values(data=graph))
        await session.execute(
            sa.update(FlowVersion).where(FlowVersion.id == 1, FlowVersion.tenant_id == 101).values(data=graph)
        )
    return graph


async def test_real_facade_reference_changing_override_is_rejected(admission):
    graph = await seed_model_graph(admission)
    with pytest.raises(ResourceReferenceInvalidError):
        await facade.prepare_saved(admission.identity, "wf", override={"llm": {"model_id": 8}})
    assert graph["nodes"][0]["data"]["group_params"][0]["params"][0]["value"] == 7


async def test_real_facade_nonreference_override_is_fresh_and_keeps_source_digest(admission):
    graph = await seed_model_graph(admission)
    result = await facade.prepare_saved(admission.identity, "wf", override={"llm": {"prompt": "runtime"}})
    assert result.graph["nodes"][0]["data"]["group_params"][0]["params"][1]["value"] == "runtime"
    assert graph["nodes"][0]["data"]["group_params"][0]["params"][1]["value"] == "original"
    assert result.configuration_digest == admission.required[0].snapshot.configuration_digest


async def test_real_open_endpoint_passes_original_user_object_to_service(monkeypatch):
    user = UserPayload(user_id=11, user_name="original", tenant_id=101, user_role=[])
    principal = service_account_principal()
    monkeypatch.setattr(endpoint, "get_open_api_operator", lambda: user)
    monkeypatch.setattr(endpoint, "get_current_open_api_principal", lambda: principal)
    monkeypatch.setattr(endpoint, "require_business_action", AsyncMock())
    monkeypatch.setattr(
        endpoint.PublishedWorkflowService, "get_workflow", AsyncMock(return_value=SimpleNamespace(name="wf"))
    )
    invocation = SimpleNamespace(session_id="session", start_time=1)
    prepare = AsyncMock(return_value=invocation)
    monkeypatch.setattr(endpoint.PublishedWorkflowService, "prepare_invocation", prepare)
    monkeypatch.setattr(endpoint.DepartmentFlowService, "ensure_lease", AsyncMock(return_value=(None, None)))
    monkeypatch.setattr(endpoint.DepartmentFlowService, "stop_renewal", AsyncMock())
    monkeypatch.setattr(endpoint.telemetry_service, "log_event", AsyncMock())

    async def events(*args, **kwargs):
        if False:
            yield

    monkeypatch.setattr(endpoint.PublishedWorkflowService, "iter_events", events)
    await endpoint.invoke_workflow(
        OpenWorkflowInvokeRequest(workflow_id="00000000-0000-0000-0000-000000000001", stream=False)
    )
    assert prepare.await_args.kwargs.get("operator") is user
    assert "operator_user_id" not in prepare.await_args.kwargs
