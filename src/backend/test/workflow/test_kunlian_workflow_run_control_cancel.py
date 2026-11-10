from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier

import pytest

from bisheng.workflow.domain.repositories.kunlian_workflow_run import RunRepository
from bisheng.workflow.domain.schemas.kunlian_workflow_invocation import RunError, RunSubject
from test.workflow.test_kunlian_workflow_interaction import interactive
from test.workflow.test_kunlian_workflow_invocation import publish, request
from test.workflow.test_kunlian_workflow_publication import SCOPE, seed

OWNER = RunSubject(7, "mock", 12)


@pytest.fixture
def control_store(invocation_registration_store):
    registration = invocation_registration_store
    seed(registration)
    publish(registration, 1, "V1 {{#input_example.question#}}", required=True)
    now = [1000]
    return RunRepository(registration, clock=lambda: now[0]), now


def kinds(row):
    return [event["kind"] for event in row.material["run_control"]["events"]]


@pytest.mark.parametrize("phase", ["QUEUED", "WAITING_INPUT", "RESUME_QUEUED", "RUNNING", "RESUMING"])
def test_cancel_wins_without_advancing_run(control_store, phase):
    runs, _ = control_store
    row, _ = runs.admit(SCOPE, OWNER.user_id, "start", interactive(), run_control=True)
    session_id = row.session_id
    claim = interaction_id = accepted = None
    answer = {"question": "private answer"}
    if phase != "QUEUED":
        claim = runs.claim(7, session_id)
    if phase in {"WAITING_INPUT", "RESUME_QUEUED", "RESUMING"}:
        assert runs.wait_for_input(7, session_id, claim, {"test": "snapshot"})
        interaction_id = runs.load(7, session_id).material["interaction_id"]
    if phase in {"RESUME_QUEUED", "RESUMING"}:
        accepted, created = runs.answer(OWNER, session_id, interaction_id, "answer", answer)
        assert created
    if phase == "RESUMING":
        claim = runs.claim_resume(7, session_id, interaction_id)

    original = runs.load(7, session_id)
    active = phase in {"RUNNING", "RESUMING"}
    canceled = runs.request_cancel(OWNER, session_id)
    assert canceled.status == ("CANCEL_REQUESTED" if active else "CANCELLED")
    assert runs.request_cancel(OWNER, session_id).material == canceled.material
    assert runs.claim(7, session_id) is None
    if active:
        finish = runs.finish_resume if phase == "RESUMING" else runs.finish
        assert not finish(7, session_id, "wrong-claim", output={"result": "late"})
        assert runs.load(7, session_id).status == "CANCEL_REQUESTED"
        finish(7, session_id, claim, output={"result": "late"})
    if interaction_id:
        assert runs.claim_resume(7, session_id, interaction_id) is None
        if accepted:
            assert runs.answer(OWNER, session_id, interaction_id, "answer", answer) == (accepted, False)
        else:
            with pytest.raises(RunError):
                runs.answer(OWNER, session_id, interaction_id, "answer", answer)
    result = runs.load(7, session_id)
    assert result.status == "CANCELLED" and result.output is None and result.error is None
    assert result.deadline_at == original.deadline_at and result.workflow_version_id == 1
    assert kinds(result)[-2:] == ["CANCEL_ACCEPTED", "CANCELLED"]
    assert "private answer" not in str(result.material)


@pytest.mark.parametrize("prior", ["success", "failure", "deadline"])
def test_cancel_preserves_previous_terminal_cause(control_store, prior):
    runs, now = control_store
    row, _ = runs.admit(SCOPE, OWNER.user_id, "start", request(question="test"), run_control=True)
    claim = runs.claim(7, row.session_id)
    if prior == "deadline":
        now[0] = runs.load(7, row.session_id).deadline_at
    else:
        assert runs.finish(
            7,
            row.session_id,
            claim,
            **({"output": {"result": "V1"}} if prior == "success" else {"error": "EXECUTION_FAILED"}),
        )

    result = runs.request_cancel(OWNER, row.session_id)
    assert (result.status, result.error, result.output) == {
        "success": ("SUCCEEDED", None, {"result": "V1"}),
        "failure": ("FAILED", "EXECUTION_FAILED", None),
        "deadline": ("FAILED", "EXECUTION_TIMEOUT", None),
    }[prior]
    assert kinds(result) == ["ACCEPTED", "STARTED", result.status]
    assert runs.request_cancel(OWNER, row.session_id).model_dump() == result.model_dump()


def test_concurrent_cancel_and_rollback_keep_events_atomic(control_store, monkeypatch):
    runs, _ = control_store
    row, _ = runs.admit(SCOPE, OWNER.user_id, "start", interactive(), run_control=True)
    transaction = runs.registration.transaction

    class Rollback(Exception):
        pass

    @contextmanager
    def fail_commit():
        with transaction() as session:
            yield session
            raise Rollback

    with monkeypatch.context() as patches:
        patches.setattr(runs.registration, "transaction", fail_commit)
        with pytest.raises(Rollback):
            runs.request_cancel(OWNER, row.session_id)

    initial = runs.load(7, row.session_id)
    assert initial.status == "QUEUED" and kinds(initial) == ["ACCEPTED"]
    barrier = Barrier(2, timeout=5)

    def cancel():
        barrier.wait()
        return runs.request_cancel(OWNER, row.session_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = [pool.submit(cancel) for _ in range(2)]
        outcomes = [job.result(timeout=5) for job in pending]
    assert [result.status for result in outcomes] == ["CANCELLED", "CANCELLED"]
    assert outcomes[0].material == outcomes[1].material
    assert kinds(runs.load(7, row.session_id)) == ["ACCEPTED", "CANCEL_ACCEPTED", "CANCELLED"]


def test_concurrent_cancel_and_success_commit_only_one_terminal_outcome(control_store):
    runs, _ = control_store
    row, _ = runs.admit(SCOPE, OWNER.user_id, "race", request(question="race"), run_control=True)
    claim = runs.claim(7, row.session_id)
    output = {"result": "V1"}
    barrier = Barrier(2, timeout=5)

    def race(operation, *args, **kwargs):
        barrier.wait()
        return operation(*args, **kwargs)

    with ThreadPoolExecutor(max_workers=2) as pool:
        finish = pool.submit(race, runs.finish, 7, row.session_id, claim, output=output)
        cancel = pool.submit(race, runs.request_cancel, OWNER, row.session_id)
        won = finish.result(timeout=5)
        response = cancel.result(timeout=5)

    terminal = runs.load(7, row.session_id)
    if won:
        assert (terminal.status, terminal.output, response.status) == ("SUCCEEDED", output, "SUCCEEDED")
        assert kinds(terminal) == ["ACCEPTED", "STARTED", "SUCCEEDED"]
    else:
        assert (terminal.status, terminal.output) == ("CANCELLED", None)
        assert response.status in {"CANCEL_REQUESTED", "CANCELLED"}
        assert kinds(terminal) == ["ACCEPTED", "STARTED", "CANCEL_ACCEPTED", "CANCELLED"]
