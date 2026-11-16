"""F133 formal admission uses publication facts, never the candidate registry."""

import pytest

from bisheng.database.models.flow import Flow, FlowStatus
from bisheng.database.models.flow_version import FlowVersion
from bisheng.workflow.domain.schemas.kunlian_workflow_invocation import RunError, RunRequest
from test.workflow.test_kunlian_workflow_publication import FLOW_ID, SCOPE, seed
from test.workflow.test_kunlian_workflow_registration_e2e import example_graph


@pytest.mark.parametrize("node_type", ["llm", "tool", "code", "knowledge_retriever", "condition"])
def test_formal_admission_accepts_existing_core_nodes(invocation_registration_store, node_type):
    runs = formal_store(invocation_registration_store)
    graph = example_graph()
    middle = {"id": "middle", "data": {"id": "middle", "type": node_type, "group_params": []}}
    graph["nodes"].insert(2, middle)
    edge = graph["edges"][1]
    target = edge["target"]
    edge["target"] = "middle"
    graph["edges"].append({**edge, "id": "middle_edge", "source": "middle", "target": target})
    with invocation_registration_store.transaction() as session:
        session.get(FlowVersion, 1).data = graph
    row, created = runs.admit(SCOPE, 12, "core", RunRequest(workflow_id=FLOW_ID, input={"question": "hello"}))
    assert created and row.material["graph"] == graph
    assert row.material["flow_user_id"] == 11


@pytest.mark.parametrize("kind", ["platform_agent", "platform_knowledge_retriever", "unregistered_type"])
def test_formal_rejects_nodes_without_runtime_context_before_admission(invocation_registration_store, kind):
    runs = formal_store(invocation_registration_store)
    graph = example_graph()
    graph["nodes"].append({"id": "unsupported", "data": {"id": "unsupported", "type": kind, "group_params": []}})
    with invocation_registration_store.transaction() as session:
        session.get(FlowVersion, 1).data = graph
    with pytest.raises(RunError, match="VERSION_UNAVAILABLE"):
        runs.admit(SCOPE, 12, "unsupported", RunRequest(workflow_id=FLOW_ID))


def test_formal_callback_uses_only_declared_output():
    from types import SimpleNamespace

    from bisheng.worker.workflow.kunlian_workflow_run import ResultCallback

    callback = ResultCallback("out", allow_intermediate=True)
    callback.on_output_msg(SimpleNamespace(node_id="llm", files=[], msg="not-final"))
    assert callback.result is None
    callback.on_output_msg(SimpleNamespace(node_id="out", files=[], msg="final"))
    assert callback.result == "final"
    with pytest.raises(RunError, match="INVALID_OUTPUT"):
        callback.on_output_msg(SimpleNamespace(node_id="out", files=[], msg="duplicate"))


def test_current_version_can_be_omitted():
    body = RunRequest(workflow_id=FLOW_ID)
    assert body.workflow_version_id is None


def formal_store(registration):
    from bisheng.workflow.domain.repositories.kunlian_registration import PublishedRunRegistrationRepository
    from bisheng.workflow.domain.repositories.kunlian_workflow_run import RunRepository

    seed(registration)
    with registration.transaction() as session:
        session.get(Flow, FLOW_ID).status = FlowStatus.ONLINE.value
        version = session.get(FlowVersion, 1)
        version.is_current = 1
        version.data = example_graph()
    return RunRepository(PublishedRunRegistrationRepository(registration.sessions))


def test_formal_admission_freezes_without_registration_and_replays_current_intent(invocation_registration_store):
    registration = invocation_registration_store
    runs = formal_store(registration)
    body = RunRequest(workflow_id=FLOW_ID, input={"question": "hello"})
    row, created = runs.admit(SCOPE, 12, "current", body, run_control=True)
    assert created and row.workflow_version_id == 1
    assert row.material["graph"] == example_graph()
    with registration.transaction() as session:
        session.get(FlowVersion, 1).is_current = 0
        version = session.get(FlowVersion, 2)
        version.is_current = 1
        version.data = example_graph()
    replay, created = runs.admit(SCOPE, 12, "current", body)
    assert not created and replay.session_id == row.session_id and replay.workflow_version_id == 1
    with pytest.raises(RunError, match="IDEMPOTENCY_CONFLICT"):
        runs.admit(SCOPE, 12, "current", RunRequest(workflow_id=FLOW_ID, workflow_version_id=1, input=body.input))
    with pytest.raises(RunError, match="VERSION_UNAVAILABLE"):
        runs.admit(SCOPE, 12, "stale", RunRequest(workflow_id=FLOW_ID, workflow_version_id=1))
    assert runs.admit(SCOPE, 12, "next", body)[0].workflow_version_id == 2


def test_request_subject_uses_stable_integration_not_rotating_key():
    from types import SimpleNamespace

    from bisheng.open_api.application.kunlian_access import KunlianRequestUser
    from bisheng.workflow.application.kunlian_runtime import run_subject_from_request

    principal = SimpleNamespace(credential_id=1, integration_id="integration", connection_id="sso", policy_revision=1)
    access = KunlianRequestUser(principal, SimpleNamespace(tenant_id=7, user_id=12), "tenant", "subject")
    first = run_subject_from_request(access)
    principal.credential_id = 2
    second = run_subject_from_request(access)
    assert first.connection_id == second.connection_id == "integration"
    assert first.credential_id == 1 and second.credential_id == 2
    assert first.identity_connection_id == "sso"


async def test_formal_service_persists_identity_and_worker_rejects_revocation(
    invocation_registration_store, monkeypatch
):
    from types import SimpleNamespace

    from bisheng.worker.workflow.kunlian_workflow_run import execute_run
    from bisheng.workflow.application import kunlian_workflow_invocation as invocation
    from bisheng.workflow.application.kunlian_runtime import create_kunlian_runtime_service
    from bisheng.workflow.domain.schemas.kunlian_workflow_invocation import RunSubject

    runs = formal_store(invocation_registration_store)
    subject = RunSubject(7, "integration", 12, 9, "sso", "tenant", "subject", 1)
    revoked = [False]

    async def resolve(value):
        if revoked[0]:
            raise RunError("FORBIDDEN")
        return SimpleNamespace(tenant_id=value.tenant_id, user_id=value.user_id)

    async def permit(*args, **kwargs):
        return None

    monkeypatch.setattr(invocation, "require_business_action", permit)
    messages = []
    service = create_kunlian_runtime_service(
        repository=runs, resolve_user=resolve, dispatch=lambda *args: messages.append(args)
    )
    row, created = await service.submit(subject, "once", RunRequest(workflow_id=FLOW_ID, input={"question": "hello"}))
    assert created and messages == [(7, row.session_id)]
    assert runs.load(7, row.session_id).material["kunlian_identity"]["credential_id"] == 9
    revoked[0] = True
    await execute_run(service, 7, row.session_id)
    failed = runs.load(7, row.session_id)
    assert failed.status == "FAILED" and failed.error == "FORBIDDEN"
    assert failed.material["kunlian_identity"]["credential_id"] == 9


async def test_formal_worker_stops_at_node_boundary_after_identity_revocation(
    invocation_registration_store, monkeypatch
):
    from types import SimpleNamespace

    from bisheng.worker.workflow.kunlian_workflow_run import execute_run
    from bisheng.workflow.application import kunlian_workflow_invocation as invocation
    from bisheng.workflow.application.kunlian_runtime import create_kunlian_runtime_service
    from bisheng.workflow.domain.schemas.kunlian_workflow_invocation import RunSubject

    runs = formal_store(invocation_registration_store)
    calls = []
    from test.workflow.kunlian_interaction_worker import fake_node_services

    fake_node_services(monkeypatch.setattr)

    async def resolve(subject):
        calls.append(subject.credential_id)
        if len(calls) >= 3:  # submit and claim succeed; first graph node is revoked.
            raise RunError("FORBIDDEN")
        return SimpleNamespace(tenant_id=7, user_id=12)

    async def permit(*args, **kwargs):
        return None

    monkeypatch.setattr(invocation, "require_business_action", permit)
    service = create_kunlian_runtime_service(repository=runs, resolve_user=resolve, dispatch=lambda *args: None)
    subject = RunSubject(7, "integration", 12, 9, "sso", "tenant", "subject", 1)
    row, _ = await service.submit(subject, "node", RunRequest(workflow_id=FLOW_ID, input={"question": "hello"}))
    await execute_run(service, 7, row.session_id)
    result = runs.load(7, row.session_id)
    assert len(calls) >= 3
    assert result.status == "FAILED" and result.output is None


@pytest.mark.parametrize("interactive", [False, True])
@pytest.mark.parametrize("with_llm", [False, True])
async def test_formal_engine_runs_frozen_graph_with_stable_owner_reference(
    invocation_registration_store, monkeypatch, interactive, with_llm
):
    from dataclasses import replace
    from types import SimpleNamespace

    from bisheng.worker.workflow.kunlian_workflow_run import execute_run
    from bisheng.workflow.application import kunlian_workflow_invocation as invocation
    from bisheng.workflow.application.kunlian_runtime import create_kunlian_runtime_service
    from bisheng.workflow.domain.schemas.kunlian_workflow_invocation import InteractionAnswer, RunSubject
    from test.workflow.kunlian_interaction_worker import fake_node_services

    runs = formal_store(invocation_registration_store)
    fake_node_services(monkeypatch.setattr)
    llm_calls = []
    if with_llm:
        from bisheng.workflow.nodes.llm.llm import LLMService

        graph = example_graph()
        llm = {
            "id": "llm_middle",
            "data": {
                "id": "llm_middle",
                "type": "llm",
                "tab": {"value": "single"},
                "group_params": [
                    {
                        "params": [
                            {"key": "model_id", "value": 1},
                            {"key": "system_prompt", "value": ""},
                            {"key": "user_prompt", "value": "{{#input_example.question#}}"},
                        ]
                    }
                ],
            },
        }
        graph["nodes"].insert(2, llm)
        target = graph["edges"][1]["target"]
        graph["edges"][1]["target"] = "llm_middle"
        graph["edges"].append(
            {
                "id": "llm_output_edge",
                "source": "llm_middle",
                "target": target,
                "sourceHandle": "right_handle",
                "targetHandle": "left_handle",
            }
        )
        graph["nodes"][3]["data"]["group_params"][0]["params"][1]["value"]["msg"] = "{{#llm_middle.output#}}"
        with invocation_registration_store.transaction() as session:
            session.get(FlowVersion, 1).data = graph

        class LocalModel:
            def invoke(self, messages, config=None):
                llm_calls.append(messages[-1].content)
                return SimpleNamespace(content="model-output")

        monkeypatch.setattr(LLMService, "get_bisheng_llm_sync", lambda **kwargs: LocalModel())

    async def resolve(subject):
        return SimpleNamespace(tenant_id=subject.tenant_id, user_id=subject.user_id)

    async def permit(*args, **kwargs):
        return None

    monkeypatch.setattr(invocation, "require_business_action", permit)
    service = create_kunlian_runtime_service(repository=runs, resolve_user=resolve, dispatch=lambda *args: None)
    subject = RunSubject(7, "integration", 12, 9, "sso", "tenant", "subject", 1)
    body = RunRequest(
        workflow_id=FLOW_ID,
        mode="interactive" if interactive else None,
        input={} if interactive else {"question": "hello"},
    )
    row, _ = await service.submit(subject, "engine", body)
    await execute_run(service, 7, row.session_id)
    rotated = replace(subject, credential_id=10)
    result = await service.query(rotated, row.session_id)
    if interactive:
        assert result.status == "WAITING_INPUT"
        interaction_id = result.material["interaction_id"]
        answer = InteractionAnswer(input={"question": "hello"})
        assert (await service.answer(rotated, row.session_id, interaction_id, "answer", answer))[1]
        assert not (await service.answer(rotated, row.session_id, interaction_id, "answer", answer))[1]
        await execute_run(service, 7, row.session_id, interaction_id)
        result = await service.query(rotated, row.session_id)
    assert result.status == "SUCCEEDED" and isinstance(result.output["result"], str)
    if with_llm:
        assert result.output == {"result": "model-output"}
        assert len(llm_calls) == 1 and "hello" in str(llm_calls[0])
    with pytest.raises(RunError, match="SESSION_NOT_FOUND"):
        await service.query(replace(rotated, connection_id="other-integration"), row.session_id)


@pytest.mark.parametrize("code, expected", [("UNAUTHENTICATED", "FORBIDDEN"), ("UNAVAILABLE", "UNAVAILABLE")])
async def test_factory_maps_authoritative_revalidation_denials(monkeypatch, code, expected):
    from bisheng.common.services.config_service import ConfigService
    from bisheng.core.config.settings import WorkflowConf
    from bisheng.open_api.application import kunlian_access
    from bisheng.open_api.domain.services.kunlian_credential import KunlianAccessError
    from bisheng.workflow.application.kunlian_runtime import get_kunlian_runtime_service

    async def reject(*args, **kwargs):
        raise KunlianAccessError(code)

    monkeypatch.setattr(kunlian_access, "revalidate_kunlian_subject", reject)
    monkeypatch.setattr(ConfigService, "get_workflow_conf", lambda self: WorkflowConf())
    service = await get_kunlian_runtime_service()
    with pytest.raises(RunError, match=expected):
        await service.resolve_user(None)


async def test_real_key_rotation_allows_query_cancel_but_blocks_origin_resume(
    invocation_registration_store, monkeypatch
):
    from types import SimpleNamespace

    from bisheng.open_api.application.kunlian_access import KunlianRequestUser, revalidate_kunlian_subject
    from bisheng.open_api.domain.services.kunlian_credential import KunlianAccessError, KunlianCredentialService
    from bisheng.worker.workflow.kunlian_workflow_run import execute_run
    from bisheng.workflow.application import kunlian_workflow_invocation as invocation
    from bisheng.workflow.application.kunlian_runtime import create_kunlian_runtime_service, run_subject_from_request
    from bisheng.workflow.domain.schemas.kunlian_workflow_invocation import InteractionAnswer
    from test.open_api.test_kunlian_credential import Store
    from test.workflow.kunlian_interaction_worker import fake_node_services

    credentials = KunlianCredentialService(Store())
    issued = await credentials.issue(
        is_global_super=True,
        created_by=1,
        connection_id="sso",
        integration_id="integration",
        tenant_ids=["external"],
        capabilities=["invoke", "read"],
    )
    user = SimpleNamespace(tenant_id=7, user_id=12, is_global_super=False)

    class Identities:
        async def resolve(self, **kwargs):
            return user

    async def resolve(subject):
        try:
            return await revalidate_kunlian_subject(subject, credentials=credentials, identities=Identities())
        except KunlianAccessError:
            raise RunError("FORBIDDEN") from None

    async def permit(*args, **kwargs):
        return None

    monkeypatch.setattr(invocation, "require_business_action", permit)
    fake_node_services(monkeypatch.setattr)
    service = create_kunlian_runtime_service(
        repository=formal_store(invocation_registration_store), resolve_user=resolve, dispatch=lambda *args: None
    )

    async def subject_for(key):
        principal = await credentials.authenticate("Bearer " + key, external_tenant_id="external", capability="invoke")
        return run_subject_from_request(KunlianRequestUser(principal, user, "external", "subject"))

    original = await subject_for(issued["api_key"])
    row, _ = await service.submit(original, "rotation", RunRequest(workflow_id=FLOW_ID, mode="interactive"))
    await execute_run(service, 7, row.session_id)
    rotated_key = await credentials.rotate(issued["id"], is_global_super=True)
    current = await subject_for(rotated_key["api_key"])
    waiting = await service.query(current, row.session_id)
    assert waiting.status == "WAITING_INPUT"
    with pytest.raises(RunError, match="FORBIDDEN"):
        await service.answer(
            current,
            row.session_id,
            waiting.material["interaction_id"],
            "answer",
            InteractionAnswer(input={"question": "hello"}),
        )
    assert service.repository.load(7, row.session_id).status == "WAITING_INPUT"
    assert (await service.cancel(current, row.session_id)).status == "CANCELLED"


def test_formal_dispatch_contains_references_not_identity(monkeypatch):
    from bisheng.worker.workflow import kunlian_runtime

    deliveries = []
    monkeypatch.setattr(kunlian_runtime.run, "apply_async", lambda **kwargs: deliveries.append(kwargs))
    kunlian_runtime.dispatch_run(7, "session", "interaction")
    assert deliveries == [{"args": ["session", "interaction"], "headers": {"tenant_id": 7}, "queue": "workflow_celery"}]
