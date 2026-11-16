"""Formal recovery never promotes candidate rows into trusted execution."""

from dataclasses import asdict

from bisheng.workflow.domain.schemas.kunlian_workflow_invocation import RunRequest, RunSubject
from test.workflow.test_kunlian_runtime import formal_store
from test.workflow.test_kunlian_workflow_publication import FLOW_ID, SCOPE


async def test_recovery_keyset_is_bounded_and_preserves_tenant_context(invocation_registration_store):
    from bisheng.core.context.tenant import get_current_tenant_id, tenant_execution_scope
    from bisheng.worker.workflow.kunlian_runtime import reconcile_batch
    from bisheng.workflow.domain.models.kunlian_workflow_run import KunlianWorkflowRun

    runs = formal_store(invocation_registration_store)
    identity = asdict(RunSubject(7, SCOPE.connection_id, 12, 1, "sso", "tenant", "subject", 1))
    body = RunRequest(workflow_id=FLOW_ID, input={"question": "hello"})
    rows = [runs.admit(SCOPE, 12, f"formal-{i}", body, run_control=True, identity=identity)[0] for i in range(3)]
    with invocation_registration_store.transaction() as session:
        other = session.get(KunlianWorkflowRun, rows[1].session_id)
        other.tenant_id = 8
        other.material = {**other.material, "kunlian_identity": {**identity, "tenant_id": 8}}
    deliveries = []

    class Service:
        repository = runs

        async def deliver(self, tenant_id, session_id, interaction_id):
            deliveries.append((tenant_id, session_id))

    cursor = None
    with tenant_execution_scope(99):
        for _ in range(3):
            cursor = await reconcile_batch(Service(), cursor, limit=1)
            assert get_current_tenant_id() == 99
        assert cursor is None
    assert set(deliveries) == {(7, rows[0].session_id), (8, rows[1].session_id), (7, rows[2].session_id)}


async def test_failed_dispatch_is_recovered_and_resume_reference_is_preserved(invocation_registration_store):
    from types import SimpleNamespace

    from bisheng.worker.workflow.kunlian_runtime import reconcile_batch
    from bisheng.workflow.application.kunlian_runtime import create_kunlian_runtime_service
    from bisheng.workflow.domain.models.kunlian_workflow_run import KunlianWorkflowRun

    runs = formal_store(invocation_registration_store)
    identity = asdict(RunSubject(7, SCOPE.connection_id, 12, 1, "sso", "tenant", "subject", 1))
    row, _ = runs.admit(SCOPE, 12, "recover", RunRequest(workflow_id=FLOW_ID), run_control=True, identity=identity)
    fail = [True]
    deliveries = []

    def dispatch(*args):
        if fail[0]:
            raise ConnectionError("unavailable")
        deliveries.append(args)

    async def resolve(subject):
        return SimpleNamespace(tenant_id=7, user_id=12)

    service = create_kunlian_runtime_service(repository=runs, resolve_user=resolve, dispatch=dispatch)
    await service.deliver(7, row.session_id)
    assert runs.load(7, row.session_id).status == "QUEUED" and not deliveries
    fail[0] = False
    await reconcile_batch(service)
    assert deliveries == [(7, row.session_id)]
    with invocation_registration_store.transaction() as session:
        resumed = session.get(KunlianWorkflowRun, row.session_id)
        resumed.status = "RESUME_QUEUED"
        resumed.material = {**resumed.material, "interaction_id": "a" * 32}
    await reconcile_batch(service)
    assert deliveries[-1] == (7, row.session_id, "a" * 32)


def test_beat_registers_bounded_formal_recovery():
    from bisheng.worker.config import beat_schedule

    assert beat_schedule["kunlian-formal-run-recovery"]["task"] == "kunlian.formal_workflow_reconcile"


async def test_recovery_retries_only_formal_rows_and_expires_queue(invocation_registration_store):
    from bisheng.worker.workflow.kunlian_runtime import reconcile_batch

    runs = formal_store(invocation_registration_store)
    now = [1000]
    runs.clock = lambda: now[0]
    identity = asdict(RunSubject(7, SCOPE.connection_id, 12, 1, "sso", "tenant", "subject", 1))
    body = RunRequest(workflow_id=FLOW_ID, input={"question": "hello"})
    formal, _ = runs.admit(SCOPE, 12, "formal", body, run_control=True, identity=identity)
    candidate, _ = runs.admit(SCOPE, 12, "candidate", body, run_control=True)
    deliveries = []

    class Service:
        repository = runs

        async def deliver(self, *args):
            deliveries.append(args)

    cursor = await reconcile_batch(Service(), limit=10)
    assert cursor is None and deliveries == [(7, formal.session_id, None)]
    now[0] += 61
    deliveries.clear()
    await reconcile_batch(Service(), limit=10)
    assert deliveries == []
    assert runs.load(7, formal.session_id).error == "QUEUE_TIMEOUT"
    assert runs.load(7, candidate.session_id).status == "QUEUED"
