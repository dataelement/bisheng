import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.flow import PlatformAgentExecutionError
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.worker.workflow.platform_agent_long_task import register_long_task_reconcile
from bisheng.workflow.application import platform_agent
from bisheng.workflow.domain.schemas.platform_agent import AgentReference, AgentRunObservation
from test.workflow.test_platform_agent_long_task_resume_output import MESSAGE, messages, ready
from test.workflow.test_platform_agent_long_task_resume_reconcile import read, start
from test.workflow.test_platform_agent_long_task_resume_reconcile import runtime as runtime
from test.workflow.test_platform_agent_long_task_resume_wait import CALL
from test.workflow.test_platform_agent_long_task_resume_wait import interaction_runtime as interaction_runtime
from test.workflow.test_platform_agent_long_task_resume_wait import long_remote as long_remote


@pytest.mark.parametrize("winner", ["stop", "success", "deadline"])
async def test_stop_and_deadline_compete_with_one_durable_output(runtime, monkeypatch, winner):
    execution_id, dispatch_id = await ready(runtime, monkeypatch)
    with tenant_execution_scope(7):
        attempt = await platform_agent.claim_long_task_resume(execution_id, CALL, dispatch_id)
        deadline = read(runtime, execution_id)[1]["deadline"]
        if winner == "success":
            await platform_agent.commit_long_task_resume_output(attempt, MESSAGE)
        elif winner == "deadline":
            runtime.now[0] = deadline
        runtime.repo.request_stop(execution_id, cancel_long=True)
        runtime.repo.request_stop(execution_id, cancel_long=True)
        with pytest.raises(PlatformAgentExecutionError):
            await platform_agent.commit_long_task_resume_output(attempt, MESSAGE)
        row, call, resume = read(runtime, execution_id)
        assert call["deadline"] == deadline
        assert row["dispatches"][dispatch_id]["state"] == "DONE"
        assert resume["phase"] == "TERMINAL" and "snapshot" not in resume and "result" not in resume
        assert len(messages(runtime)) == (winner == "success")
        assert (
            call["long_task"]["local_state"]
            == {"stop": "STOPPED", "success": "SUCCEEDED", "deadline": "TIMED_OUT"}[winner]
        )
        assert row["state"] == {"stop": "ABORTED", "success": "SUCCEEDED", "deadline": "FAILED"}[winner]


@pytest.mark.parametrize("stage", ["poll", "recovery"])
async def test_scan_closes_expired_work_and_fences_old_owner(runtime, monkeypatch, stage):
    if stage == "recovery":
        execution_id, dispatch_id = await ready(runtime, monkeypatch)
    else:
        execution_id, dispatch_id = await start(runtime, monkeypatch)
    with tenant_execution_scope(7):
        _, original, _ = read(runtime, execution_id)
        if stage == "poll":
            lease, _ = runtime.repo.claim_long_task_resume_poll(execution_id, CALL, 7)
        else:
            attempt = await platform_agent.claim_long_task_resume(execution_id, CALL, dispatch_id)
        runtime.now[0] = original["deadline"]
        assert runtime.repo.due_long_calls(7, resume_recovery=True)[0] == [(execution_id, CALL)]
        await runtime.service.reconcile_long(7, execution_id, CALL)
        if stage == "poll":
            observation = AgentRunObservation(
                run_id=original["agent_run_id"], ref=AgentReference.model_validate(original["ref"]), status="SUCCEEDED"
            )
            assert not runtime.repo.finish_long_task_resume_poll(execution_id, CALL, lease, observation=observation)
        else:
            assert not runtime.repo.fail_long_task_resume(attempt["dispatch"], CALL, "RUN_FAILED")
            with pytest.raises(PlatformAgentExecutionError):
                await platform_agent.commit_long_task_resume_output(attempt, MESSAGE)
            assert not messages(runtime)
        row, call, resume = read(runtime, execution_id)
    assert call["deadline"] == original["deadline"] and call["long_task"]["local_state"] == "TIMED_OUT"
    assert row["state"] == "FAILED" and row["dispatches"][dispatch_id]["state"] == "DONE"
    assert resume["phase"] == "TERMINAL" and not runtime.outputs


async def test_deadline_during_output_flush_rolls_back_message(runtime, monkeypatch):
    from bisheng.chat_session.application import workflow_output

    execution_id, dispatch_id = await ready(runtime, monkeypatch)
    write = workflow_output.write_output
    with tenant_execution_scope(7):
        attempt = await platform_agent.claim_long_task_resume(execution_id, CALL, dispatch_id)
        deadline = read(runtime, execution_id)[1]["deadline"]

        def expire_after_flush(*args, **kwargs):
            message_id = write(*args, **kwargs)
            runtime.now[0] = deadline
            return message_id

        monkeypatch.setattr(workflow_output, "write_output", expire_after_flush)
        with pytest.raises(PlatformAgentExecutionError):
            await platform_agent.commit_long_task_resume_output(attempt, MESSAGE)
        await runtime.service.reconcile_long(7, execution_id, CALL)
        _, call, resume = read(runtime, execution_id)
        assert call["long_task"]["local_state"] == "TIMED_OUT"
        assert resume["phase"] == "TERMINAL" and not messages(runtime)


@pytest.mark.parametrize("unknown_start", [False, True])
async def test_lost_cancel_wakeup_is_scanned_and_acceptance_is_not_terminal(runtime, monkeypatch, unknown_start):
    execution_id, _ = await start(runtime, monkeypatch, failure=TimeoutError if unknown_start else None)
    app = SimpleNamespace(task=lambda **_options: lambda func: func)
    reconcile, _ = register_long_task_reconcile(app, lambda: runtime.service)
    cancel = AsyncMock(wraps=runtime.provider.cancel)
    monkeypatch.setattr(runtime.provider, "cancel", cancel)

    def scan(tenant_id):
        reconcile.request = SimpleNamespace(headers={"tenant_id": tenant_id})
        reconcile()

    with tenant_execution_scope(7):
        _, original, _ = read(runtime, execution_id)
        runtime.repo.request_stop(execution_id, cancel_long=True)
        runtime.repo.request_stop(execution_id, cancel_long=True)
        row, call, resume = read(runtime, execution_id)
        assert resume["phase"] == "TERMINAL" and row["state"] == "ABORTED"
        assert call["long_task"]["cancel_state"] == "INTENT"
    await asyncio.to_thread(scan, 8)
    cancel.assert_not_awaited()
    await asyncio.to_thread(scan, 7)
    with tenant_execution_scope(7):
        _, accepted, _ = read(runtime, execution_id)
        assert accepted["long_task"]["cancel_state"] == "ACCEPTED"
        assert accepted["long_task"]["remote_state"] == "RUNNING"
    runtime.now[0] += 1
    await asyncio.to_thread(scan, 7)
    with tenant_execution_scope(7):
        _, confirmed, resume = read(runtime, execution_id)
    assert confirmed["long_task"]["cancel_state"] == "CONFIRMED"
    assert confirmed["long_task"]["remote_state"] == "CANCELLED"
    assert confirmed["deadline"] == original["deadline"] and resume["phase"] == "TERMINAL"
    cancel.assert_awaited_once()
    assert cancel.await_args.args[-2:] == (confirmed["agent_run_id"], f"{execution_id}:{CALL}:cancel")


@pytest.mark.parametrize("remote", ["REJECTED", "UNCONFIRMED", "SUCCEEDED"])
async def test_cancel_outcomes_cannot_reopen_a_stopped_execution(runtime, monkeypatch, remote):
    execution_id, _ = await start(runtime, monkeypatch)
    cancel = AsyncMock(return_value="REJECTED" if remote == "REJECTED" else "ACCEPTED")
    monkeypatch.setattr(runtime.provider, "cancel", cancel)
    with tenant_execution_scope(7):
        lease, _ = runtime.repo.claim_long_task_resume_poll(execution_id, CALL, 7)
        runtime.repo.request_stop(execution_id, cancel_long=True)
        if remote == "SUCCEEDED":
            runtime.now[0] += 3
        await runtime.service.reconcile_long(7, execution_id, CALL)
        if remote == "UNCONFIRMED":
            _, call, _ = read(runtime, execution_id)
            assert call["long_task"]["cancel_state"] == "ACCEPTED"
            runtime.now[0] = call["long_task"]["reconcile_until"]
            await runtime.service.reconcile_long(7, execution_id, CALL)
        row, call, resume = read(runtime, execution_id)
        assert not runtime.repo.finish_long_task_resume_poll(execution_id, CALL, lease)
        assert call["long_task"]["cancel_state"] == ("NO_ACTION" if remote == "SUCCEEDED" else remote)
        assert call["long_task"]["remote_state"] == ("SUCCEEDED" if remote == "SUCCEEDED" else "RUNNING")
        assert row["state"] == "ABORTED" and resume["phase"] == "TERMINAL"
        assert not runtime.outputs and all(item["kind"] == "START" for item in row["dispatches"].values())
    assert cancel.await_count == (0 if remote == "SUCCEEDED" else 1)
