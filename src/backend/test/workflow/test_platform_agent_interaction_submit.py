import asyncio
from contextlib import contextmanager
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.flow import (
    PlatformAgentExecutionError,
    PlatformAgentNonterminalError,
    PlatformAgentOutputError,
    PlatformAgentUnknownError,
    PlatformAgentUpstreamError,
)
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.workflow.domain.repositories.platform_agent import PlatformAgentRepository
from test.workflow.test_platform_agent_interaction_wait import (
    AGENT_ID,
    prepare,
    run_worker,
    sample_graph,
)
from test.workflow.test_platform_agent_interaction_wait import (
    interaction_runtime as interaction_runtime,
)
from test.workflow.test_platform_agent_interaction_wait import (
    long_remote as long_remote,
)

CALL = f"{AGENT_ID}:0"


async def waiting(runtime, version="v1"):
    with tenant_execution_scope(7):
        execution, initial = await prepare(runtime, sample_graph(version))
        await asyncio.to_thread(run_worker, execution, initial)
        execution_id = execution["execution_id"]
        data = runtime.repo.long_snapshot(execution_id, CALL)["interaction"]
        return execution_id, data["interaction_id"], data["form"]["revision"]


async def test_duplicate_submission_has_one_persisted_dispatch_across_connections(interaction_runtime):
    runtime = interaction_runtime
    target = await waiting(runtime)
    sessions = runtime.repo.sessions

    @contextmanager
    def serialized_sqlite_sessions():
        # SQLite 不实现 SELECT FOR UPDATE。用独立连接的写事务模拟行锁串行。
        with sessions() as session:
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            yield session

    first = PlatformAgentRepository(serialized_sqlite_sessions, clock=runtime.repo.clock)
    second = PlatformAgentRepository(serialized_sqlite_sessions, clock=runtime.repo.clock)
    actor = await runtime.service._long_actor(runtime.user, runtime.repo.get_execution(target[0]))

    def submit(repo, interaction, revision, key, answer):
        with tenant_execution_scope(7):
            return repo.accept_interaction_answer(target[0], CALL, actor, interaction, revision, key, answer)

    for interaction, revision, answer in [(target[1], "old", "ok"), ("wrong", target[2], "ok"), (*target[1:], " ")]:
        with pytest.raises(PlatformAgentExecutionError):
            submit(first, interaction, revision, "same", answer)
    with tenant_execution_scope(7):
        input_deadline = runtime.repo.long_snapshot(target[0], CALL)["deadline"]
    runtime.now[0] = input_deadline - 1
    one, two = await asyncio.gather(
        asyncio.to_thread(submit, first, *target[1:], "same", "ok"),
        asyncio.to_thread(submit, second, *target[1:], "same", "ok"),
    )
    assert one["dispatch_id"] == two["dispatch_id"]
    for key, answer in [("same", "changed"), ("another", "ok")]:
        with pytest.raises(PlatformAgentExecutionError):
            submit(second, *target[1:], key, answer)
    with tenant_execution_scope(7):
        record = runtime.repo.get_execution(target[0])
        assert len(record["dispatches"]) == 2
        call = record["calls"][CALL]
        assert call["deadline"] > input_deadline
        runtime.now[0] = input_deadline + 1
        assert submit(second, *target[1:], "same", "ok")["expires_at"] == call["deadline"]


@pytest.mark.parametrize(
    ("scenario", "error", "reason"),
    [
        ("lost", None, None),
        ("unconfirmed", PlatformAgentUnknownError, "SUBMIT_UNKNOWN"),
        ("lookup_unavailable", PlatformAgentUnknownError, "SUBMIT_UNKNOWN"),
        ("reject", PlatformAgentUpstreamError, "SUBMIT_REJECTED"),
        ("result_wait", PlatformAgentUnknownError, "RESULT_UNAVAILABLE"),
        ("wrong_run", PlatformAgentOutputError, "RUN_FAILED"),
        ("second_form", PlatformAgentNonterminalError, "UNSUPPORTED_INPUT"),
    ],
)
async def test_resume_checks_original_receipt_and_result(interaction_runtime, monkeypatch, scenario, error, reason):
    runtime = interaction_runtime
    provider = runtime.service.provider
    target = await waiting(runtime, scenario if scenario in {"lost", "reject"} else "v1")
    events = []
    original_submit = provider.submit_interaction
    if scenario in {"unconfirmed", "lookup_unavailable"}:
        original_submit = AsyncMock(side_effect=TimeoutError)
    if scenario == "lookup_unavailable":
        monkeypatch.setattr(provider, "lookup_submission", AsyncMock(side_effect=ConnectionError))
    submit = AsyncMock(side_effect=original_submit)
    monkeypatch.setattr(provider, "submit_interaction", submit)
    if scenario in {"result_wait", "wrong_run"}:
        real_result = provider.get_result

        async def get_result(*args):
            result = await real_result(*args)
            if scenario == "wrong_run" and result:
                return result.model_copy(update={"agent_run_id": "another"})
            return None

        monkeypatch.setattr(provider, "get_result", get_result)
    if scenario == "second_form":
        real_status = provider.get_status

        async def get_status(actor, ref, run_id):
            status = await real_status(actor, ref, run_id)
            if status.status == "RUNNING":
                return status.model_copy(
                    update={
                        "status": "WAITING_INPUT",
                        "interaction": provider._interaction(run_id).model_copy(update={"revision": "2"}),
                    }
                )
            return status

        monkeypatch.setattr(provider, "get_status", get_status)

    with tenant_execution_scope(7):
        actor = await runtime.service._long_actor(runtime.user, runtime.repo.get_execution(target[0]))
        receipt = runtime.repo.accept_interaction_answer(target[0], CALL, actor, *target[1:], "key", "answer")
        dispatch = runtime.repo.claim_dispatch(target[0], receipt["dispatch_id"])
        run = runtime.service.resume_long_interaction(runtime.user, dispatch, CALL, events.append)
        if error:
            with pytest.raises(error):
                await run
            assert runtime.repo.long_snapshot(target[0], CALL)["reason"] == reason
        else:
            assert (await run)["answer"] == "answer"
            assert any(event.get("interaction_phase") == "SUBMIT_UNKNOWN" for event in events)
        assert submit.await_count == (2 if scenario == "unconfirmed" else 1)
        assert not runtime.repo.claim_dispatch(target[0], receipt["dispatch_id"])
