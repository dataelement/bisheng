from copy import deepcopy

import pytest

from bisheng.database.models.flow_version import FlowVersion
from bisheng.workflow.domain.repositories.kunlian_workflow_run import RunRepository
from bisheng.workflow.domain.schemas.kunlian_workflow_invocation import RunError, RunRequest
from bisheng.workflow.domain.services.kunlian_descriptor import prepare_descriptor
from test.workflow.test_kunlian_workflow_publication import FLOW_ID, SCOPE, seed
from test.workflow.test_kunlian_workflow_registration_e2e import example_graph


def publish(registration, version_id, marker, *, with_input=True, output_files=None, required=False):
    graph = example_graph()
    params = graph["nodes"][2]["data"]["group_params"][0]["params"]
    params[1]["value"]["msg"] = marker
    graph["nodes"][1]["data"]["group_params"][0]["params"][0]["value"][0]["required"] = required
    if output_files:
        params.append({"key": "output_msg", "value": {"msg": marker, "files": output_files}})
    if not with_input:
        graph["nodes"].pop(1)
        graph["edges"].pop(0)
        graph["edges"][0]["source"] = graph["nodes"][0]["id"]
    with registration.transaction() as session:
        session.get(FlowVersion, version_id).data = graph
    flow, version, revision = registration.candidate(SCOPE, FLOW_ID, version_id)
    descriptor = prepare_descriptor(flow, version, graph, {}, {})
    assert descriptor is not None
    registration.publish(SCOPE, FLOW_ID, version_id, revision, descriptor, {}, {})


@pytest.fixture
def run_store(invocation_registration_store):
    registration_store = invocation_registration_store
    seed(registration_store)
    publish(registration_store, 1, "V1 {{#input_example.question#}}")
    now = [1000]
    return RunRepository(registration_store, clock=lambda: now[0]), registration_store, now


def request(version=1, **inputs):
    return RunRequest(workflow_id=FLOW_ID, workflow_version_id=version, input=inputs)


def test_same_key_submissions_on_independent_connections_return_one_session(run_store):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    runs, _, _ = run_store
    gate = Barrier(2)

    def submit():
        gate.wait(timeout=5)
        return runs.admit(SCOPE, 12, "same-call", request(question="input"))

    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = [pool.submit(submit) for _ in range(2)]
        results = [future.result(timeout=10) for future in pending]
    assert sum(created for _, created in results) == 1
    assert len({record.session_id for record, _ in results}) == 1


def test_admission_freezes_publication_and_replays_after_replacement(run_store):
    runs, registration, _ = run_store
    body = request(question="test")
    run, created = runs.admit(SCOPE, 12, "call-1", body)
    assert created and run.status == "QUEUED"
    frozen = deepcopy(run.material)
    publish(registration, 2, "V2")
    assert runs.load(SCOPE.tenant_id, run.session_id).material == frozen
    replay, created = runs.admit(SCOPE, 12, "call-1", body)
    assert not created and replay.session_id == run.session_id
    with pytest.raises(RunError, match="IDEMPOTENCY_CONFLICT"):
        runs.admit(SCOPE, 12, "call-1", request(2, question="test"))
    with pytest.raises(RunError, match="VERSION_UNAVAILABLE"):
        runs.admit(SCOPE, 12, "call-2", body)
    with pytest.raises(RunError, match="INVALID_INPUT"):
        runs.admit(SCOPE, 12, "call-3", request(2, unexpected="test"))
    assert runs.admit(SCOPE, 12, "call-3", request(2, question="test"))[1]


def test_attachment_output_alias_cannot_bypass_minimal_graph_scope(run_store):
    runs, registration, _ = run_store
    publish(registration, 2, "V2", output_files=[{"path": "file"}])
    assert registration.version(SCOPE, FLOW_ID, 2)["availability"] == "AVAILABLE"
    with pytest.raises(RunError, match="VERSION_UNAVAILABLE"):
        runs.admit(SCOPE, 12, "attachments", request(2))


def test_case_insensitive_storage_cannot_cross_connection_scope(run_store):
    from dataclasses import replace

    from sqlalchemy import event

    runs, registration, now = run_store
    record, _ = runs.admit(SCOPE, 12, "same-key", request())
    other = replace(SCOPE, connection_id=SCOPE.connection_id.upper())
    with registration.transaction() as session:
        engine = session.get_bind()

    def fold_connection(_conn, _cursor, statement, parameters, _context, _executemany):
        for table in ("workflow_kl_run", "workflow_kl_version"):
            statement = statement.replace(f"{table}.connection_id =", f"{table}.connection_id COLLATE NOCASE =")
        return statement, parameters

    event.listen(engine, "before_cursor_execute", fold_connection, retval=True)
    try:
        with pytest.raises(RunError, match="FORBIDDEN"):
            runs.admit(other, 12, "same-key", request())
        with pytest.raises(RunError, match="VERSION_UNAVAILABLE"):
            runs.admit(other, 12, "new-key", request())
        assert runs.reconcile(other) == []
        now[0] += runs.queue_seconds
        runs.reconcile(other)
        assert runs.load(SCOPE.tenant_id, record.session_id).status == "QUEUED"
        runs.reconcile(SCOPE)
        assert runs.load(SCOPE.tenant_id, record.session_id).error == "QUEUE_TIMEOUT"
    finally:
        event.remove(engine, "before_cursor_execute", fold_connection)


async def test_authorization_uses_resolved_user_instead_of_ambient_actor(run_store, monkeypatch):
    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.common.errcode.http_error import UnAuthorizedError
    from bisheng.permission.application import relation_api
    from bisheng.permission.application.identity import (
        PermissionActor,
        get_current_permission_actor,
        reset_current_permission_actor,
        resolve_permission_actor,
        set_current_permission_actor,
    )
    from bisheng.public_endpoints.domain.context import (
        PublicApiPrincipal,
        get_current_public_api_principal,
        reset_current_public_api_principal,
        set_current_public_api_principal,
    )
    from bisheng.workflow.application import kunlian_workflow_invocation as invocation

    runs, _, _ = run_store
    subject = invocation.RunSubject(7, "mock", 12)

    async def resolve(value):
        return UserPayload(user_id=value.user_id, tenant_id=value.tenant_id, user_role=[])

    async def is_admin(*_):
        return False

    async def require(user, **_):
        actor = await resolve_permission_actor(user)
        if get_current_public_api_principal() is None and actor.subject_id == 12:
            raise UnAuthorizedError()

    monkeypatch.setattr(relation_api, "is_tenant_admin", is_admin)
    monkeypatch.setattr(invocation, "require_business_action", require)
    messages = []
    service = invocation.WorkflowInvocationService(runs, resolve, lambda *args: messages.append(args))
    parent = PermissionActor(subject_type="service_account", subject_id=11, tenant_id=7)
    guest = PublicApiPrincipal(
        tenant_id=7, operator_user_id=11, operator_name="A", resource_type="workflow", resource_id=FLOW_ID
    )
    token = set_current_permission_actor(parent)
    guest_token = set_current_public_api_principal(guest)
    try:
        with pytest.raises(RunError, match="FORBIDDEN"):
            await service.submit(subject, "call-1", request())
        assert get_current_permission_actor() is parent
        assert get_current_public_api_principal() is guest
        assert messages == []
    finally:
        reset_current_public_api_principal(guest_token)
        reset_current_permission_actor(token)


async def test_current_permission_is_required_for_replay(run_store, monkeypatch):
    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.common.errcode.http_error import UnAuthorizedError
    from bisheng.workflow.application import kunlian_workflow_invocation as invocation

    runs, _, _ = run_store
    subject = invocation.RunSubject(7, "mock", 12)
    allowed = True

    async def resolve(value):
        assert value == subject
        return UserPayload(user_id=12, tenant_id=7, user_role=[])

    async def authorize(user, **kwargs):
        assert user.user_id == 12 and kwargs["action"] == "use"
        if not allowed:
            raise UnAuthorizedError()

    monkeypatch.setattr(invocation, "require_business_action", authorize)
    messages = []
    service = invocation.WorkflowInvocationService(runs, resolve, lambda *args: messages.append(args))
    record, created = await service.submit(subject, "call-1", request())
    assert created and messages == [(7, record.session_id)]
    allowed = False
    with pytest.raises(RunError, match="FORBIDDEN"):
        await service.submit(subject, "call-1", request())
    assert len(messages) == 1


async def test_worker_claim_and_compensation_preserve_terminal_state(run_store, monkeypatch):
    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.worker.workflow import kunlian_workflow_run as worker
    from bisheng.workflow.application import kunlian_workflow_invocation as invocation

    runs, _, now = run_store
    dispatches, executions = [], []
    authorized = True

    async def resolve(subject):
        return UserPayload(user_id=subject.user_id, tenant_id=subject.tenant_id, user_role=[])

    async def authorize(user, **kwargs):
        from bisheng.common.errcode.http_error import UnAuthorizedError

        assert user.user_id == 12 and kwargs["action"] == "use"
        if not authorized:
            raise UnAuthorizedError()

    def dispatch(*args):
        dispatches.append(args)
        if len(dispatches) == 1:
            raise OSError("broker result unknown")

    def execute(run, user):
        executions.append(run.session_id)
        return {"result": str(user.user_id)}

    monkeypatch.setattr(invocation, "require_business_action", authorize)
    monkeypatch.setattr(worker, "execute_graph", execute)
    service = invocation.WorkflowInvocationService(runs, resolve, dispatch)
    subject = invocation.RunSubject(7, "mock", 12)
    record, _ = await service.submit(subject, "call-1", request())
    await service.reconcile(SCOPE)
    assert dispatches == [(7, record.session_id)] * 2
    await worker.execute_run(service, 8, record.session_id)
    for tenant_id, session_id in dispatches:
        await worker.execute_run(service, tenant_id, session_id)
    result = await service.query(subject, record.session_id)
    assert result.status == "SUCCEEDED" and result.output == {"result": "12"}
    assert result.material is None and executions == [record.session_id]

    revoked, _ = await service.submit(subject, "revoked", request())
    authorized = False
    await worker.execute_run(service, 7, revoked.session_id)
    authorized = True
    assert (await service.query(subject, revoked.session_id)).error == "FORBIDDEN"
    assert executions == [record.session_id]

    lost, _ = await service.submit(subject, "call-2", request())
    claim = runs.claim(7, lost.session_id)
    assert claim
    running = await service.query(subject, lost.session_id)
    assert running.status == "RUNNING" and running.output is None
    now[0] += runs.run_seconds
    await service.reconcile(SCOPE)
    assert not runs.finish(7, lost.session_id, claim, output={"result": "late"})
    assert (await service.query(subject, lost.session_id)).error == "EXECUTION_TIMEOUT"
    now[0] += runs.retain_seconds
    await service.reconcile(SCOPE)
    from bisheng.workflow.domain.models.kunlian_workflow_run import KunlianWorkflowRun

    with runs.registration.transaction() as session:
        assert session.get(KunlianWorkflowRun, record.session_id).output is None
    with pytest.raises(RunError, match="SESSION_NOT_FOUND"):
        await service.query(subject, lost.session_id)
    with pytest.raises(RunError, match="IDEMPOTENCY_EXPIRED"):
        await service.submit(subject, "call-2", request())
