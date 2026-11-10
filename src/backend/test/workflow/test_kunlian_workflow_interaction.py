from copy import deepcopy

import pytest

from bisheng.workflow.domain.repositories.kunlian_workflow_run import RunRepository
from bisheng.workflow.domain.schemas.kunlian_workflow_invocation import RunError, RunRequest
from bisheng.workflow.domain.schemas.platform_agent import canonical_digest
from test.workflow.test_kunlian_workflow_invocation import publish, request
from test.workflow.test_kunlian_workflow_publication import FLOW_ID, SCOPE, seed


def interactive(version=1, **inputs):
    return RunRequest(workflow_id=FLOW_ID, workflow_version_id=version, input=inputs, mode="interactive")


@pytest.fixture
def run_store(invocation_registration_store):
    registration = invocation_registration_store
    seed(registration)
    publish(registration, 1, "V1 {{#input_example.question#}}", required=True)
    now = [1000]
    return RunRepository(registration, clock=lambda: now[0]), registration, now


def test_mode_freezes_form_and_keeps_legacy_digest(run_store):
    runs, registration, _ = run_store
    legacy = request(question="legacy")
    old, _ = runs.admit(SCOPE, 12, "legacy", legacy)
    assert old.request_digest == canonical_digest(
        {"workflow_id": FLOW_ID, "workflow_version_id": 1, "input": {"question": "legacy"}}
    )
    assert "mode" not in old.material
    with pytest.raises(RunError, match="IDEMPOTENCY_CONFLICT"):
        runs.admit(SCOPE, 12, "legacy", interactive())

    row, _ = runs.admit(SCOPE, 12, "interactive", interactive())
    assert row.material["mode"] == "interactive"
    assert row.material["input_schema"]["required"] == ["question"]
    publish(registration, 2, "V2", with_input=False)
    assert runs.admit(SCOPE, 12, "interactive", interactive())[0].session_id == row.session_id
    with pytest.raises(RunError, match="VERSION_UNAVAILABLE"):
        runs.admit(SCOPE, 12, "no-form", interactive(2))


def test_interactive_cannot_receive_pre_supplied_answers(run_store):
    runs, _, _ = run_store
    with pytest.raises(RunError, match="INVALID_INPUT"):
        runs.admit(SCOPE, 12, "filled", interactive(question="already answered"))


def test_snapshot_restores_context_and_rejects_invalid_material(run_store, monkeypatch):
    from types import SimpleNamespace

    from bisheng.worker.workflow.kunlian_workflow_run import build_workflow, graph_result
    from bisheng.workflow.common.workflow import WorkflowStatus
    from bisheng.workflow.graph.kunlian_interaction import capture_wait, prepare_thread, restore_wait
    from test.workflow.kunlian_interaction_worker import fake_node_services

    runs, _, _ = run_store
    row, _ = runs.admit(SCOPE, 12, "snapshot", interactive())
    user = SimpleNamespace(tenant_id=7, user_id=12)
    with monkeypatch.context() as patches:
        starts = fake_node_services(patches.setattr)
        workflow, callback = build_workflow(row, user)
        prepare_thread(workflow, row.session_id)
        assert workflow.run()[0] == WorkflowStatus.INPUT.value
        snapshot = capture_wait(workflow, row, callback.input_node)
        assert starts == [12]
        for key, invalid in (
            ("format", 99),
            ("graph_digest", "changed"),
            ("input_node", "wrong"),
            ("variables", {}),
            ("variables", {"start_example": {}}),
            ("steps", {"start_example": True}),
            ("checkpoint", {**snapshot["checkpoint"], "v": 99}),
        ):
            material = deepcopy(snapshot)
            material[key] = invalid
            rebuilt, _ = build_workflow(row, user)
            with pytest.raises(RunError, match="RESUME_STATE_INVALID"):
                restore_wait(rebuilt, row, material)
        rebuilt, result = build_workflow(row, user)
        restore_wait(rebuilt, row, snapshot)
        assert rebuilt.graph_engine.graph_state.variables_pool == snapshot["variables"]
        assert rebuilt.graph_engine.nodes_map["start_example"].current_step == 1
        status, _ = rebuilt.run({"input_example": {"question": "answer"}})
        assert graph_result(status, result) == {"result": "V1 answer"}
        assert starts == [12]


@pytest.fixture
async def waiting_run(run_store, monkeypatch):
    from types import SimpleNamespace

    from bisheng.worker.workflow.kunlian_workflow_run import execute_run
    from test.workflow.kunlian_interaction_worker import fake_node_services

    runs, _, _ = run_store
    queued, _ = runs.admit(SCOPE, 12, "waiting", interactive())

    async def authorize(row):
        return SimpleNamespace(user_id=row.user_id, tenant_id=row.tenant_id)

    starts = fake_node_services(monkeypatch.setattr)
    service = SimpleNamespace(repository=runs, authorize_run=authorize)
    await execute_run(service, 7, queued.session_id)
    waiting = runs.load(7, queued.session_id)
    assert waiting.status == "WAITING_INPUT" and waiting.claim_id is None and waiting.material["snapshot"]
    return waiting, service, starts


async def test_concurrent_answer_is_accepted_once_and_not_reexecuted(run_store, waiting_run, monkeypatch):
    from asyncio import gather
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from bisheng.worker.workflow.kunlian_workflow_run import execute_run
    from bisheng.workflow.domain.schemas.kunlian_workflow_invocation import RunSubject
    from bisheng.workflow.nodes.input.input import InputNode

    runs, _, _ = run_store
    waiting, service, starts = waiting_run
    ident = waiting.material["interaction_id"]
    subject = RunSubject(7, "mock", 12)
    gate = Barrier(2)
    input_runs = []
    original = InputNode._run

    def count_input(node, unique_id):
        input_runs.append(node.id)
        return original(node, unique_id)

    monkeypatch.setattr(InputNode, "_run", count_input)

    with pytest.raises(RunError, match="INVALID_INPUT"):
        runs.answer(subject, waiting.session_id, ident, "answer-key", {})
    assert runs.load(7, waiting.session_id).status == "WAITING_INPUT"

    def submit():
        gate.wait(timeout=5)
        return runs.answer(subject, waiting.session_id, ident, "answer-key", {"question": "answer"})

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [pool.submit(submit) for _ in range(2)]
        first, second = [future.result(timeout=10) for future in results]
    assert first[0] == second[0] and first[1] != second[1]

    for key, answer, error in (
        ("answer-key", "changed", "IDEMPOTENCY_CONFLICT"),
        ("other-key", "answer", "INTERACTION_CONSUMED"),
    ):
        with pytest.raises(RunError, match=error):
            runs.answer(subject, waiting.session_id, ident, key, {"question": answer})

    await execute_run(service, 7, waiting.session_id)
    await execute_run(service, 7, waiting.session_id, "f" * 32)
    assert runs.load(7, waiting.session_id).status == "RESUME_QUEUED"
    await gather(
        execute_run(service, 7, waiting.session_id, ident),
        execute_run(service, 7, waiting.session_id, ident),
    )
    result = runs.load(7, waiting.session_id)
    assert result.status == "SUCCEEDED" and result.output == {"result": "V1 answer"}
    assert starts == [12] and input_runs == ["input_example"]
    assert set(result.material) == {"interaction_id", "receipt"}
    assert runs.answer(subject, waiting.session_id, ident, "answer-key", {"question": "answer"}) == (first[0], False)


def test_waiting_deadline_and_submission_compete_on_original_run(run_store, waiting_run):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from bisheng.workflow.domain.schemas.kunlian_workflow_invocation import RunSubject

    runs, _, now = run_store
    waiting, _, _ = waiting_run
    ident = waiting.material["interaction_id"]
    subject = RunSubject(7, "mock", 12)
    gate = Barrier(2)
    now[0] = waiting.deadline_at

    def submit():
        gate.wait(timeout=5)
        with pytest.raises(RunError, match="INPUT_TIMEOUT"):
            runs.answer(subject, waiting.session_id, ident, "too-late", {"question": "late"})

    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(submit)
        gate.wait(timeout=5)
        assert runs.reconcile(SCOPE, include_resumes=True) == []
        pending.result(timeout=10)
    terminal = runs.load(7, waiting.session_id)
    assert terminal.status == "FAILED" and terminal.error == "INPUT_TIMEOUT"
    assert terminal.material == {"interaction_id": ident}


def test_lost_or_expired_initial_claim_cannot_publish_waiting_form(run_store):
    runs, _, now = run_store
    row, _ = runs.admit(SCOPE, 12, "stale-claim", interactive())
    claim = runs.claim(7, row.session_id)
    assert claim
    assert not runs.wait_for_input(7, row.session_id, "old-claim", {})
    now[0] += runs.run_seconds
    assert not runs.wait_for_input(7, row.session_id, claim, {})
    runs.reconcile(SCOPE)
    failed = runs.load(7, row.session_id)
    assert failed.status == "FAILED" and failed.error == "EXECUTION_TIMEOUT" and failed.material is None


@pytest.mark.parametrize("phase", ["claim", "finish"])
def test_initial_deadline_is_checked_after_waiting_for_database(run_store, phase):
    from sqlalchemy import event

    runs, registration, now = run_store
    row, _ = runs.admit(SCOPE, 12, "blocked", interactive())
    claim = None
    if phase == "claim":
        expected = "QUEUE_TIMEOUT"
    else:
        claim = runs.claim(7, row.session_id)
        assert claim
        row = runs.load(7, row.session_id)
        expected = "EXECUTION_TIMEOUT"
    now[0] = row.deadline_at - 1
    with registration.transaction() as db:
        engine = db.get_bind()

    def advance_clock(_conn, _cursor, statement, _params, _ctx, _many):
        # SQLite 没有行锁,在第一次运行行查询或更新时模拟等待跨过截止时间。
        if "workflow_kl_run" in statement:
            now[0] = row.deadline_at

    event.listen(engine, "before_cursor_execute", advance_clock)
    try:
        changed = (
            runs.finish(7, row.session_id, claim, error="EXECUTION_FAILED") if claim else runs.claim(7, row.session_id)
        )
        assert not changed
    finally:
        event.remove(engine, "before_cursor_execute", advance_clock)
    runs.reconcile(SCOPE)
    terminal = runs.load(7, row.session_id)
    assert terminal.status == "FAILED" and terminal.error == expected


async def test_omitted_optional_text_does_not_become_the_form_label(run_store, waiting_run):
    from bisheng.worker.workflow.kunlian_workflow_run import execute_run
    from bisheng.workflow.domain.schemas.kunlian_workflow_invocation import RunSubject

    runs, registration, _ = run_store
    _, service, _ = waiting_run
    publish(registration, 2, "V2 [{{#input_example.question#}}]")
    initial, _ = runs.admit(SCOPE, 12, "optional", interactive(2))
    await execute_run(service, 7, initial.session_id)
    row = runs.load(7, initial.session_id)
    interaction_id = row.material["interaction_id"]
    runs.answer(RunSubject(7, "mock", 12), initial.session_id, interaction_id, "empty", {})
    await execute_run(service, 7, initial.session_id, interaction_id)
    result = runs.load(7, initial.session_id)
    assert result.status == "SUCCEEDED" and result.output == {"result": "V2 []"}


async def test_broken_resume_envelope_does_not_block_compensation_for_other_runs(run_store, waiting_run):
    from bisheng.worker.workflow.kunlian_workflow_run import execute_run
    from bisheng.workflow.domain.models.kunlian_workflow_run import KunlianWorkflowRun
    from bisheng.workflow.domain.schemas.kunlian_workflow_invocation import RunSubject

    runs, registration, _ = run_store
    broken, service, _ = waiting_run
    sibling, _ = runs.admit(SCOPE, 12, "sibling", interactive())
    await execute_run(service, 7, sibling.session_id)
    sibling = runs.load(7, sibling.session_id)
    subject = RunSubject(7, "mock", 12)
    for row in (broken, sibling):
        runs.answer(subject, row.session_id, row.material["interaction_id"], "answer", {"question": "answer"})
    with registration.transaction() as db:
        row = db.get(KunlianWorkflowRun, broken.session_id)
        row.material = {key: value for key, value in row.material.items() if key != "interaction_id"}

    assert runs.reconcile(SCOPE, include_resumes=True) == [(sibling.session_id, sibling.material["interaction_id"])]
    failed = runs.load(7, broken.session_id)
    assert failed.status == "FAILED" and failed.error == "RESUME_STATE_INVALID"
    assert "answer" not in (failed.material or {}) and "snapshot" not in (failed.material or {})


@pytest.mark.parametrize(
    "outcome", ["queue_timeout", "execution_timeout", "invalid_snapshot", "changed_answer", "revoked"]
)
async def test_resume_failures_keep_receipt_and_clear_private_material(run_store, waiting_run, outcome, monkeypatch):
    from bisheng.common.errcode.permission import PermissionServiceUnavailableError
    from bisheng.worker.workflow.kunlian_workflow_run import execute_run
    from bisheng.workflow.domain.models.kunlian_workflow_run import KunlianWorkflowRun
    from bisheng.workflow.domain.schemas.kunlian_workflow_invocation import RunSubject

    runs, registration, now = run_store
    waiting, service, _ = waiting_run
    session_id, ident = waiting.session_id, waiting.material["interaction_id"]
    subject = RunSubject(7, "mock", 12)
    answer = {"question": "private answer"}
    now[0] = waiting.deadline_at - 1
    receipt, _ = runs.answer(subject, session_id, ident, "answer", answer)
    now[0] = waiting.deadline_at  # 等待截止不影响已经受理的答案。
    assert runs.reconcile(SCOPE, include_resumes=True) == [(session_id, ident)]

    if outcome == "queue_timeout":

        async def unavailable(_):
            raise PermissionServiceUnavailableError()

        monkeypatch.setattr(service, "authorize_run", unavailable)
        await execute_run(service, 7, session_id, ident)
        assert runs.load(7, session_id).status == "RESUME_QUEUED"
        now[0] = runs.load(7, session_id).deadline_at
        runs.reconcile(SCOPE)
        error = "RESUME_QUEUE_TIMEOUT"
    elif outcome == "execution_timeout":
        claim = runs.claim_resume(7, session_id, ident)
        assert claim
        assert not runs.finish_resume(7, session_id, "old-claim", output={"result": "wrong claim"})
        now[0] = runs.load(7, session_id).deadline_at
        assert not runs.finish_resume(7, session_id, claim, output={"result": "late"})
        runs.reconcile(SCOPE)
        error = "RESUME_EXECUTION_TIMEOUT"
    elif outcome in {"invalid_snapshot", "changed_answer"}:
        with registration.transaction() as db:
            row = db.get(KunlianWorkflowRun, session_id)
            damage = (
                {"snapshot": {"format": 999}} if outcome == "invalid_snapshot" else {"answer": {"question": "other"}}
            )
            row.material = {**row.material, **damage}
        await execute_run(service, 7, session_id, ident)
        error = "RESUME_STATE_INVALID"
    else:

        async def denied(_):
            raise RunError("FORBIDDEN")

        monkeypatch.setattr(service, "authorize_run", denied)
        await execute_run(service, 7, session_id, ident)
        error = "FORBIDDEN"

    terminal = runs.load(7, session_id)
    assert terminal.status == "FAILED" and terminal.error == error
    assert set(terminal.material) == {"interaction_id", "receipt"}
    assert "private answer" not in str(terminal.material)
    assert runs.answer(subject, session_id, ident, "answer", answer) == (receipt, False)
    now[0] = terminal.expires_at
    runs.reconcile(SCOPE)
    with registration.transaction() as db:
        expired = db.get(KunlianWorkflowRun, session_id)
        assert expired.material is None and expired.output is None and expired.request_digest
    with pytest.raises(RunError, match="IDEMPOTENCY_EXPIRED"):
        runs.admit(SCOPE, 12, "waiting", interactive())
