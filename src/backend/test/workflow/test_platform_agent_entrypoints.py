"""覆盖 AC: AC-08, AC-10, AC-11, AC-12, AC-17, AC-19, AC-20, AC-22, AC-25。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.flow import PlatformAgentConfigurationError, PlatformAgentError, PlatformAgentExecutionError
from bisheng.common.errcode.tenant_resolver import TokenVersionMismatchError
from bisheng.core.config.settings import PlatformAgentConf
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.workflow.application import platform_agent as application
from bisheng.workflow.domain.schemas.platform_agent import PUBLICATION_KEY
from bisheng.workflow.domain.services import platform_agent_service as domain
from test.workflow.test_platform_agent_node import node_data


@pytest.mark.asyncio
async def test_admission_freezes_actual_user_and_claims_once(agent_store, monkeypatch):
    repo, _, _, _ = agent_store
    service = domain.PlatformAgentService(
        config=PlatformAgentConf(mode="mock", mock_subjects={"7:12": "B"}), repository=repo
    )
    monkeypatch.setattr(application, "get_service", lambda: service)
    authorization = AsyncMock()
    monkeypatch.setattr(domain, "require_business_action", authorization)
    user = SimpleNamespace(user_id=12, tenant_id=7)
    graph = {"nodes": [{"data": node_data()}], "edges": []}
    graph["nodes"][0]["data"]["group_params"][0]["params"][1]["value"].pop("value")
    with pytest.raises(PlatformAgentConfigurationError):
        await service.admit(user, "f" * 32, "session", graph, "DEBUG", override={"platform_agent_1": {"agent_ref": {}}})
    execution, dispatch_id = await service.admit(user, "f" * 32, "session", graph, "DEBUG")
    reference = {"execution_id": execution["execution_id"], "dispatch_id": dispatch_id}
    with application.queue_tenant_scope({"tenant_id": 7}, reference):
        assert get_current_tenant_id() == 7
        context = await application.claim_queued_execution(reference, "f" * 32, "session", 12)
        assert context["login_user"].user_id == 12
        assert await application.claim_queued_execution(reference, "f" * 32, "session", 12) is None
        with pytest.raises(PlatformAgentExecutionError):
            await application.claim_queued_execution(reference, "f" * 32, "session", 11)
    assert get_current_tenant_id() != 7
    assert authorization.await_count >= 2
    assert PUBLICATION_KEY not in graph


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["schema", "credentials"])
async def test_debug_admission_binds_schema_and_rejects_drift_before_invoke(agent_store, monkeypatch, change):
    import time
    from copy import deepcopy

    from bisheng.common.errcode.flow import PlatformAgentVersionError

    repo, _, _, _ = agent_store
    repo.clock = time.time
    service = domain.PlatformAgentService(
        config=PlatformAgentConf(mode="mock", mock_subjects={"7:12": "B"}), repository=repo
    )
    provider = service.provider
    service._provider = provider
    monkeypatch.setattr(domain, "require_business_action", AsyncMock())
    node = node_data()
    node["group_params"][0]["params"][1]["value"].pop("value")
    graph = {"nodes": [{"data": node}], "edges": []}
    user = SimpleNamespace(user_id=12, tenant_id=7)
    execution, dispatch_id = await service.admit(user, "f" * 32, "schema-drift", graph, "DEBUG")
    get_version = provider.get_version

    async def changed_version(*args):
        version = deepcopy(await get_version(*args))
        version.output_schema["properties"]["extra"] = {"type": "boolean"}
        return version

    if change == "schema":
        monkeypatch.setattr(provider, "get_version", changed_version)
    else:
        service.identity_reader = AsyncMock(return_value={12: {"state": "active", "tenant_id": 7, "token_version": 1}})
    invoke = AsyncMock(wraps=provider.invoke)
    monkeypatch.setattr(provider, "invoke", invoke)
    dispatch = repo.claim_dispatch(execution["execution_id"], dispatch_id)
    with pytest.raises(PlatformAgentVersionError if change == "schema" else TokenVersionMismatchError):
        await service.invoke_node(user, "f" * 32, dispatch, node, 0, lambda _: None)
    invoke.assert_not_awaited()
    assert PUBLICATION_KEY not in graph


@pytest.mark.parametrize(
    "failure", ["permission", "credentials", "environment", "environment-after-run", "construction", "resume-missing"]
)
def test_worker_failure_finishes_only_the_owned_execution_with_safe_reason(agent_store, monkeypatch, failure):
    from unittest.mock import Mock

    from bisheng.common.errcode.flow import (
        PlatformAgentEnvironmentError,
        PlatformAgentPermissionError,
        PlatformAgentUpstreamError,
    )
    from bisheng.common.errcode.http_error import UnAuthorizedError
    from bisheng.worker.workflow import tasks
    from bisheng.workflow.domain.schemas.platform_agent import VerifiedAgentActor

    repo, _, graph, _ = agent_store
    config = PlatformAgentConf(mode="mock")
    service = domain.PlatformAgentService(config=config, repository=repo)
    monkeypatch.setattr(application, "get_service", lambda: service)
    monkeypatch.setattr(
        domain,
        "require_business_action",
        AsyncMock(side_effect=UnAuthorizedError() if failure == "permission" else None),
    )
    execution, dispatch_id = repo.prepare_execution(
        "f" * 32, "failed-session", VerifiedAgentActor(12, 7), graph, config, "DEBUG"
    )
    if failure == "environment":
        service.config = config.model_copy(update={"policy_revision": "new-policy"})
    if failure == "credentials":
        service.identity_reader = AsyncMock(return_value={12: {"state": "active", "tenant_id": 7, "token_version": 1}})
    if failure == "resume-missing":
        first = repo.claim_dispatch(execution["execution_id"], dispatch_id)
        repo.finish_execution(first, "WAITING")
        dispatch_id = repo.prepare_resume(execution["execution_id"], VerifiedAgentActor(12, 7))
    reference = {"execution_id": execution["execution_id"], "dispatch_id": dispatch_id}
    task = tasks.continue_workflow if failure == "resume-missing" else tasks.execute_workflow
    monkeypatch.setattr(task, "request", SimpleNamespace(headers={"tenant_id": 7}), raising=False)
    monkeypatch.setattr(tasks, "_log_workflow_telemetry", Mock())
    monkeypatch.setattr(
        tasks, "settings", SimpleNamespace(get_workflow_conf=lambda: SimpleNamespace(max_steps=10, timeout=30))
    )
    monkeypatch.setattr(
        tasks.FlowDao, "get_flow_by_id", lambda _: SimpleNamespace(tenant_id=7, user_id=11, name="fixture")
    )
    monkeypatch.setattr(tasks, "Workflow", Mock(side_effect=RuntimeError("secret-probe")))
    if failure == "environment-after-run":

        def construct(*args, **kwargs):
            def run():
                service.config = config.model_copy(update={"policy_revision": "new-policy"})

            return SimpleNamespace(
                graph_engine=SimpleNamespace(platform_agent_context=kwargs["platform_agent_context"]),
                run=run,
                status=lambda: "SUCCESS",
                reason=lambda: "",
            )

        monkeypatch.setattr(tasks, "Workflow", construct)
    callback = Mock(unique_id="failed-session")
    monkeypatch.setattr(tasks, "RedisCallback", lambda *args, **kwargs: callback)
    monkeypatch.setattr(tasks, "_global_workflow", {})
    # 外层任务可重抛已公开的领域错误。必须先结束其已领取执行。
    logged = []
    sink = tasks.logger.add(lambda message: logged.append(str(message)), level="ERROR", backtrace=False, diagnose=False)
    try:
        with pytest.raises((PlatformAgentError, TokenVersionMismatchError)):
            task.run("failed-session", "f" * 32, "chat", 12, platform_agent_execution=reference)
    finally:
        tasks.logger.remove(sink)
    assert repo.get_execution(execution["execution_id"])["state"] == "FAILED"
    callback.bind_platform_agent_execution.assert_called_with(execution["execution_id"])
    reason = callback.set_workflow_status.call_args.args[1]
    expected = (
        TokenVersionMismatchError
        if failure == "credentials"
        else PlatformAgentPermissionError
        if failure == "permission"
        else PlatformAgentEnvironmentError
        if failure in {"environment", "environment-after-run"}
        else PlatformAgentUpstreamError
    )
    assert reason == expected.Msg
    assert "secret-probe" not in str(callback.mock_calls)
    assert "secret-probe" not in "".join(logged)
    before = callback.set_workflow_status.call_count
    task.run("failed-session", "f" * 32, "chat", 12, platform_agent_execution=reference)
    assert callback.set_workflow_status.call_count == before


@pytest.mark.parametrize("subject,effective", [("service_account", None), ("user", 11)])
def test_service_owner_and_forged_delegation_cannot_become_actual_user(subject, effective):
    with pytest.raises(PlatformAgentExecutionError):
        application.actual_user_from_snapshot(
            SimpleNamespace(authorization_subject_type=subject, effective_user_id=effective, tenant_id=7), 12
        )


@pytest.mark.asyncio
async def test_browser_port_keeps_ordinary_flows_independent_of_platform_agent(agent_store, monkeypatch):
    from unittest.mock import Mock

    repo, _, graph, _ = agent_store
    factory = Mock(side_effect=AssertionError("ordinary workflows must not request a provider"))
    monkeypatch.setattr(application, "get_service", factory)
    runtime = application.BrowserPlatformAgentRuntime(repo)
    assert (
        await runtime.prepare(SimpleNamespace(user_id=12, tenant_id=7), "f" * 32, "ordinary", graph, published=True)
        is None
    )
    factory.assert_not_called()


def test_worker_duplicate_does_not_start_or_overwrite_a_run(agent_store, monkeypatch):
    from unittest.mock import Mock

    from bisheng.worker.workflow import tasks
    from bisheng.workflow.domain.schemas.platform_agent import VerifiedAgentActor

    repo, _, graph, _ = agent_store
    service = domain.PlatformAgentService(config=PlatformAgentConf(mode="mock"), repository=repo)
    monkeypatch.setattr(application, "get_service", lambda: service)
    monkeypatch.setattr(domain, "require_business_action", AsyncMock())
    execution, dispatch_id = repo.prepare_execution(
        "f" * 32, "queue-session", VerifiedAgentActor(12, 7), graph, service.config, "DEBUG"
    )
    reference = {"execution_id": execution["execution_id"], "dispatch_id": dispatch_id}
    monkeypatch.setattr(tasks.execute_workflow, "request", SimpleNamespace(headers={"tenant_id": 7}), raising=False)
    runner = Mock()
    monkeypatch.setattr(tasks, "_execute_workflow", runner)
    monkeypatch.setattr(tasks, "_log_workflow_telemetry", Mock())
    tasks.execute_workflow.run("queue-session", "f" * 32, "", 12, platform_agent_execution=reference)
    tasks.execute_workflow.run("queue-session", "f" * 32, "", 12, platform_agent_execution=reference)
    assert runner.call_count == 1
    assert runner.call_args.args[-1]["login_user"].user_id == 12
    assert get_current_tenant_id() != 7


@pytest.mark.asyncio
async def test_resume_replaces_owner_and_checks_the_dispatch_kind(agent_store, monkeypatch):
    from bisheng.workflow.domain.schemas.platform_agent import VerifiedAgentActor

    repo, _, graph, _ = agent_store
    config = PlatformAgentConf(mode="mock")
    service = domain.PlatformAgentService(config=config, repository=repo)
    monkeypatch.setattr(application, "get_service", lambda: service)
    monkeypatch.setattr(domain, "require_business_action", AsyncMock())
    actor = VerifiedAgentActor(12, 7)
    execution, first_id = repo.prepare_execution("f" * 32, "resume", actor, graph, config, "DEBUG")
    first = repo.claim_dispatch(execution["execution_id"], first_id)
    repo.finish_execution(first, "WAITING")
    resumed_id = repo.prepare_resume(first.execution_id, actor)
    ref = {"execution_id": first.execution_id, "dispatch_id": resumed_id}
    with application.queue_tenant_scope({"tenant_id": 7}, ref):
        with pytest.raises(PlatformAgentExecutionError):
            await application.claim_queued_execution(ref, "f" * 32, "resume", 12)
        context = await application.claim_queued_execution(ref, "f" * 32, "resume", 12, dispatch_kind="RESUME")
        assert context["dispatch"].owner != first.owner
        with pytest.raises(PlatformAgentExecutionError):
            repo.reserve_call(first, "node", 0, "digest", {}, 1005)
        assert not repo.fail_execution(first)
        repo.reserve_call(context["dispatch"], "node", 0, "digest", {}, 1005)


def test_old_unreferenced_message_does_not_change_the_new_session(monkeypatch):
    from unittest.mock import Mock

    from bisheng.worker.workflow import tasks

    graph = {"nodes": [{"data": node_data()}], "edges": []}
    callback = Mock()
    callback.get_workflow_data.return_value = graph
    monkeypatch.setattr(tasks, "RedisCallback", lambda *args, **kwargs: callback)
    monkeypatch.setattr(tasks.FlowDao, "get_flow_by_id", lambda _: SimpleNamespace(tenant_id=7, user_id=11))
    tasks._execute_workflow("session", "f" * 32, "chat", 12)
    callback.set_workflow_status.assert_not_called()


def test_old_callback_is_isolated_from_new_execution_namespaces():
    from unittest.mock import Mock

    from bisheng.worker.workflow.redis_callback import RedisCallback

    old = object.__new__(RedisCallback)
    new = object.__new__(RedisCallback)
    redis = Mock()
    redis.get.return_value = "b" * 32
    for callback, identifier in ((old, "a" * 32), (new, "b" * 32)):
        callback.unique_id = "session"
        callback.redis_client = redis
        callback.platform_agent_key = "workflow:session:platform-agent"
        callback.bind_platform_agent_execution(identifier)
    assert old.workflow_status_key != new.workflow_status_key
    old.set_workflow_status("SUCCESS")
    old.insert_workflow_response({"message": "late"})
    old.set_workflow_stop()
    redis.set.assert_not_called()
    redis.rpush.assert_not_called()


@pytest.fixture
async def published_mock(agent_store, monkeypatch):
    from bisheng.database.models.flow_version import FlowVersion

    repo, sessions, _, _ = agent_store
    graph = {"nodes": [{"data": node_data()}], "edges": []}
    graph["nodes"][0]["data"]["group_params"][0]["params"][1]["value"]["value"] = {"source": "constant", "value": 0}
    with sessions() as session:
        version = session.get(FlowVersion, 1)
        version.data = graph
        session.add(version)
        session.commit()
    service = domain.PlatformAgentService(
        config=PlatformAgentConf(mode="mock", mock_subjects={"7:11": "A", "7:12": "B"}), repository=repo
    )
    monkeypatch.setattr(application, "get_service", lambda: service)
    monkeypatch.setattr(domain, "require_business_action", AsyncMock())
    await service.publish(SimpleNamespace(user_id=11, tenant_id=7), "f" * 32, 1)
    return service, SimpleNamespace(**repo.get_workflow("f" * 32))


@pytest.mark.asyncio
@pytest.mark.parametrize("queue_failure", [False, True])
async def test_open_entry_saves_actual_b_before_dispatch_and_records_queue_failure(
    published_mock, monkeypatch, queue_failure
):
    from unittest.mock import Mock

    from bisheng.open_api.domain.context import OpenApiExecutionSnapshot
    from bisheng.workflow.domain.services import published_workflow_service as entry

    service, flow = published_mock
    callback = Mock()
    callback.get_workflow_status.return_value = None
    monkeypatch.setattr(entry, "RedisCallback", lambda *args, **kwargs: callback)
    monkeypatch.setattr(entry.PublishedWorkflowService, "get_workflow", AsyncMock(return_value=flow))
    monkeypatch.setattr(entry.ChatSessionService, "get_subject_session_if_exists", AsyncMock(return_value=None))
    monkeypatch.setattr(entry.ChatSessionService, "create_subject_session", AsyncMock())
    monkeypatch.setattr(entry.workflow_stateful_worker, "find_task_node", AsyncMock(return_value="fixture-queue"))
    dispatched = []

    def send(args, **options):
        ref = options["kwargs"]["platform_agent_execution"]
        execution = service.repository.get_execution(ref["execution_id"])
        assert execution["user_id"] == 12 and execution["state"] == "READY"
        assert execution["graph_snapshot"] == flow.data
        assert options["headers"]["tenant_id"] == 7
        dispatched.append(ref)
        if queue_failure:
            raise RuntimeError("fixture queue unavailable")

    monkeypatch.setattr(entry.execute_workflow, "apply_async", send)
    snapshot = OpenApiExecutionSnapshot(
        tenant_id=7,
        actor_kind="natural_person",
        actor_id=12,
        authorization_subject_type="user",
        authorization_subject_id=12,
        resource_owner_user_id=None,
        effective_user_id=12,
        mode="S",
        credential_id=1,
        trace_id="fixture",
        channel="open_api_v2",
    )

    async def prepare():
        return await entry.PublishedWorkflowService.prepare_invocation(
            workflow_id=flow.id,
            operator_user_id=12,
            session_subject=SimpleNamespace(),
            execution_snapshot=snapshot,
            session_id=None,
            override=None,
            user_input=None,
            message_id=None,
        )

    if queue_failure:
        with pytest.raises(RuntimeError):
            await prepare()
    else:
        await prepare()
    row = service.repository.get_execution(dispatched[0]["execution_id"])
    assert row["state"] == ("ABORTED" if queue_failure else "READY")


@pytest.mark.asyncio
@pytest.mark.parametrize("queue_failure", [False, True])
async def test_browser_entry_uses_server_publication_instead_of_payload_version(
    published_mock, monkeypatch, queue_failure
):
    from copy import deepcopy
    from unittest.mock import Mock

    from bisheng.common.chat.clients import workflow_client as entry

    service, flow = published_mock
    callback = Mock()
    callback.async_set_workflow_data = AsyncMock()
    callback.async_set_workflow_status = AsyncMock()
    monkeypatch.setattr(entry, "RedisCallback", lambda *args, **kwargs: callback)
    monkeypatch.setattr(entry.FlowDao, "get_flow_by_id", lambda _: flow)
    send = Mock(side_effect=RuntimeError("secret-probe") if queue_failure else None)
    monkeypatch.setattr(entry.execute_workflow, "apply_async", send)
    client = object.__new__(entry.WorkflowClient)
    client.kwargs = {"platform_agent_runtime": application.BrowserPlatformAgentRuntime(service.repository)}
    client.user_id = 12
    client.login_user = SimpleNamespace(user_id=12, tenant_id=7)
    client.client_id, client.chat_id, client.workflow = flow.id, "fixture-chat", None
    client.execution_snapshot = None
    client.check_status = AsyncMock(return_value=(True, "browser-session"))
    client.get_execute_worker = AsyncMock(return_value="fixture-queue")
    client.send_response = AsyncMock()
    client.workflow_run = AsyncMock(return_value=True)
    tampered = deepcopy(flow.data)
    tampered["nodes"][0]["data"]["group_params"][0]["params"][0]["value"]["version_id"] = "v2"
    await client.init_workflow({"flow_id": flow.id, "data": tampered})
    ref = send.call_args.kwargs["kwargs"]["platform_agent_execution"]
    row = service.repository.get_execution(ref["execution_id"])
    assert row["user_id"] == 12 and row["graph_snapshot"] == flow.data
    assert row["state"] == ("ABORTED" if queue_failure else "READY")
    assert "secret-probe" not in str(client.send_response.mock_calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["resume", "redis-failure", "credentials"])
async def test_browser_resume_checks_identity_before_input_and_aborts_failed_handoff(
    published_mock, monkeypatch, outcome
):
    from unittest.mock import Mock

    from bisheng.common.chat.clients import workflow_client as entry
    from bisheng.common.errcode.flow import PlatformAgentUpstreamError
    from bisheng.workflow.domain.schemas.platform_agent import VerifiedAgentActor

    service, flow = published_mock
    repo = service.repository
    execution, dispatch_id = repo.prepare_execution(
        flow.id, "browser-resume", VerifiedAgentActor(12, 7), flow.data, service.config, "PUBLISHED"
    )
    dispatch = repo.claim_dispatch(execution["execution_id"], dispatch_id)
    repo.finish_execution(dispatch, "WAITING")
    callback = Mock(unique_id="browser-resume", workflow_id=flow.id, chat_id="chat")
    callback.get_platform_agent_reference.return_value = execution["execution_id"]
    callback.async_get_workflow_status = AsyncMock(return_value={"status": "INPUT"})
    callback.async_set_user_input = AsyncMock(
        side_effect=RuntimeError("secret-probe") if outcome == "redis-failure" else None
    )
    callback.async_set_workflow_status = AsyncMock()
    client = object.__new__(entry.WorkflowClient)
    client.kwargs = {"platform_agent_runtime": application.BrowserPlatformAgentRuntime(repo)}
    client.user_id, client.login_user = 12, SimpleNamespace(user_id=12, tenant_id=7)
    client.client_id, client.chat_id, client.workflow = flow.id, "chat", callback
    client.execution_snapshot = None
    client.ensure_workflow_available = AsyncMock(return_value=True)
    client.get_execute_worker = AsyncMock(return_value="fixture-queue")
    client.workflow_run = AsyncMock()
    send = Mock()
    monkeypatch.setattr(entry.continue_workflow, "apply_async", send)
    if outcome == "credentials":
        service.identity_reader = AsyncMock(return_value={12: {"state": "active", "tenant_id": 7, "token_version": 1}})
    if outcome == "resume":
        await client.handle_user_input({"input": {"data": "hello"}})
        reference = send.call_args.kwargs["kwargs"]["platform_agent_execution"]
        assert reference["execution_id"] == execution["execution_id"] and reference["dispatch_id"] != dispatch_id
        assert repo.get_execution(execution["execution_id"])["dispatches"][reference["dispatch_id"]]["kind"] == "RESUME"
    else:
        with pytest.raises(
            TokenVersionMismatchError if outcome == "credentials" else PlatformAgentUpstreamError
        ) as error:
            await client.handle_user_input({"input": {"data": "hello"}})
        assert "secret-probe" not in str(error.value)
        send.assert_not_called()
        if outcome == "credentials":
            callback.async_set_user_input.assert_not_awaited()
    assert (
        repo.get_execution(execution["execution_id"])["state"]
        == {"resume": "READY", "redis-failure": "ABORTED", "credentials": "WAITING"}[outcome]
    )
