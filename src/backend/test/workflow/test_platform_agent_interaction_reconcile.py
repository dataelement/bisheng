import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from bisheng.common.errcode.flow import PlatformAgentExecutionError, PlatformAgentUnknownError
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.worker.workflow.platform_agent_long_task import register_long_task_reconcile
from bisheng.workflow.domain.models.platform_agent_execution import PlatformAgentExecution
from bisheng.workflow.domain.repositories.platform_agent import PlatformAgentRepository
from bisheng.workflow.domain.schemas.platform_agent import AgentReference
from test.workflow.test_platform_agent_interaction_submit import CALL, waiting
from test.workflow.test_platform_agent_interaction_submit import (
    interaction_runtime as interaction_runtime,
)
from test.workflow.test_platform_agent_interaction_submit import (
    long_remote as long_remote,
)


async def submit(runtime, target):
    execution_id, interaction_id, revision = target
    return await runtime.service.submit_interaction_answer(
        runtime.user, execution_id, CALL, interaction_id, revision, "same-key", "answer"
    )


def assert_sealed(task):
    assert {"answer", "form", "snapshot"}.isdisjoint(task["interaction"])


@pytest.mark.parametrize("boundary", ["before-permit", "before-transport", "in-flight"])
async def test_stop_fences_submission_and_preserves_only_receipt(interaction_runtime, monkeypatch, boundary):
    runtime = interaction_runtime
    repo = runtime.repo
    other = PlatformAgentRepository(repo.sessions, clock=repo.clock)
    provider = runtime.service.provider
    target = await waiting(runtime)
    execution_id = target[0]
    with tenant_execution_scope(7):
        ack = await submit(runtime, target)
        dispatch = repo.claim_dispatch(execution_id, ack["dispatch_id"])
        permit = repo.permit_interaction_submit
        send = provider.submit_interaction

        def stop():
            other.request_stop(execution_id, cancel_long=True)

        def permit_then_stop(*args, **kwargs):
            if boundary == "before-permit":
                stop()
            permit(*args, **kwargs)
            if boundary == "before-transport":
                stop()

        async def send_then_stop(*args):
            receipt = await send(*args)
            stop()
            return receipt

        monkeypatch.setattr(repo, "permit_interaction_submit", permit_then_stop)
        monkeypatch.setattr(provider, "submit_interaction", AsyncMock(side_effect=send_then_stop))
        monkeypatch.setattr(provider, "cancel", AsyncMock(wraps=provider.cancel))
        with pytest.raises(PlatformAgentExecutionError):
            await runtime.service.resume_long_interaction(runtime.user, dispatch, CALL)
        assert provider.submit_interaction.await_count == int(boundary == "in-flight")
        before = repo.long_snapshot(execution_id, CALL)
        assert_sealed(before)
        assert (before["local_state"], before["cancel_state"]) == ("STOPPED", "INTENT")
        replay = await submit(runtime, target)
        assert replay["dispatch_id"] == ack["dispatch_id"]
        assert replay["status_version"] > ack["status_version"]
        await runtime.service.reconcile_long(7, execution_id, CALL)
        runtime.now[0] += 1
        await runtime.service.reconcile_long(7, execution_id, CALL)
        after = repo.long_snapshot(execution_id, CALL)
        assert after["local_state"] == "STOPPED"
        assert after["cancel_state"] == "CONFIRMED"
        assert after["interaction"].get("remote_receipt") == ("ACCEPTED" if boundary == "in-flight" else None)
        assert provider.cancel.await_count == 1
        assert provider.cancel.await_args.args[-2:] == (before["run_id"], f"{execution_id}:{CALL}:cancel")
        assert repo.get_execution(execution_id)["state"] == "ABORTED"
        assert not runtime.outputs


@pytest.mark.parametrize(
    ("phase", "reason"),
    [
        ("WAITING_INPUT", "INPUT_TIMEOUT"),
        ("SUBMIT_QUEUED", "SUBMIT_TIMEOUT"),
        ("SUBMIT_IN_FLIGHT", "SUBMIT_UNKNOWN"),
        ("SUBMIT_UNKNOWN", "SUBMIT_UNKNOWN"),
        ("WAITING_RESULT", "RUN_TIMEOUT"),
    ],
)
async def test_phase_deadlines_converge_without_replaying_graph(interaction_runtime, phase, reason):
    runtime = interaction_runtime
    repo = runtime.repo
    other = PlatformAgentRepository(repo.sessions, clock=repo.clock)
    target = await waiting(runtime)
    execution_id = target[0]
    with tenant_execution_scope(7):
        initial = repo.long_snapshot(execution_id, CALL)
        assert initial["deadline"] - repo.clock() == 120
        dispatch = None
        if phase != "WAITING_INPUT":
            ack = await submit(runtime, target)
            assert ack["expires_at"] - repo.clock() == 30
        if phase in {"SUBMIT_IN_FLIGHT", "SUBMIT_UNKNOWN", "WAITING_RESULT"}:
            dispatch = repo.claim_dispatch(execution_id, ack["dispatch_id"])
            repo.permit_interaction_submit(dispatch, CALL)
            if phase == "SUBMIT_UNKNOWN":
                repo.mark_interaction_unknown(dispatch, CALL)
            if phase == "WAITING_RESULT":
                task = repo.long_snapshot(execution_id, CALL)
                interaction = task["interaction"]
                form = runtime.service.provider._interaction(task["run_id"])
                actor = await runtime.service._long_actor(runtime.user, task)
                receipt = await runtime.service.provider.submit_interaction(
                    actor,
                    AgentReference.model_validate(task["ref"]),
                    task["run_id"],
                    form,
                    interaction["answer"],
                    interaction["remote_key"],
                )
                runtime.now[0] += 1
                repo.record_interaction_receipt(dispatch, CALL, receipt)
        task = repo.long_snapshot(execution_id, CALL)
        assert task["interaction"]["phase"] == phase
        if phase == "WAITING_RESULT":
            assert task["deadline"] - repo.clock() == 30
            # 模拟远端仍在处理。此时只验证本地结果等待超时。
            runtime.service.provider.get_status = AsyncMock(
                return_value=(
                    await runtime.service.provider.get_status(
                        actor, AgentReference.model_validate(task["ref"]), task["run_id"]
                    )
                ).model_copy(update={"status": "RUNNING", "interaction": None})
            )
        runtime.now[0] = task["deadline"]
        assert (execution_id, CALL) in other.due_long_calls(7)[0]
        if phase == "WAITING_INPUT":
            with pytest.raises(PlatformAgentExecutionError):
                await submit(runtime, target)
        await runtime.service.reconcile_long(7, execution_id, CALL)
        closed = other.long_snapshot(execution_id, CALL)
        assert (closed["local_state"], closed["reason"]) == ("TIMED_OUT", reason)
        assert closed["reconcile_until"] - repo.clock() == 15
        assert_sealed(closed)
        assert other.get_execution(execution_id)["state"] == "FAILED"
        if dispatch:
            with pytest.raises(PlatformAgentExecutionError):
                other.ready_long_output(dispatch, CALL)
        runtime.now[0] = closed["reconcile_until"]
        await runtime.service.reconcile_long(7, execution_id, CALL)
        assert other.long_snapshot(execution_id, CALL)["cancel_state"] == "UNCONFIRMED"
        assert not runtime.outputs


@pytest.mark.parametrize("terminal", ["stop", "timeout"])
async def test_late_success_cannot_open_output_gate(interaction_runtime, monkeypatch, terminal):
    runtime = interaction_runtime
    repo = runtime.repo
    other = PlatformAgentRepository(repo.sessions, clock=repo.clock)
    provider = runtime.service.provider
    target = await waiting(runtime)
    execution_id = target[0]
    get_result = provider.get_result

    async def late_result(*args):
        result = await get_result(*args)
        assert result.status == "SUCCEEDED"
        if terminal == "stop":
            other.request_stop(execution_id, cancel_long=True)
        else:
            runtime.now[0] = other.long_snapshot(execution_id, CALL)["deadline"]
        return result

    monkeypatch.setattr(provider, "get_result", late_result)
    with tenant_execution_scope(7):
        ack = await submit(runtime, target)
        dispatch = repo.claim_dispatch(execution_id, ack["dispatch_id"])
        error = PlatformAgentExecutionError if terminal == "stop" else PlatformAgentUnknownError
        with pytest.raises(error):
            await runtime.service.resume_long_interaction(runtime.user, dispatch, CALL)
        with pytest.raises(PlatformAgentExecutionError):
            with repo.output_scope(dispatch, CALL.rsplit(":", 1)[0], 0, runtime.service.config):
                pytest.fail("迟到结果进入输出门禁")
        task = other.long_snapshot(execution_id, CALL)
        assert task["remote_state"] == "SUCCEEDED"
        assert task["local_state"] == ("STOPPED" if terminal == "stop" else "TIMED_OUT")
        assert not task.get("result_ready")
        assert_sealed(task)
        assert not runtime.outputs


async def test_scan_redelivers_original_dispatch_only_until_claimed(interaction_runtime):
    runtime = interaction_runtime
    repo = runtime.repo
    target = await waiting(runtime)
    execution_id, interaction_id, _ = target
    resume_task = Mock()
    resume_task.apply_async.side_effect = [ConnectionError, None]

    def task(**_options):
        def decorate(function):
            function.apply_async = Mock(side_effect=ConnectionError)
            return function

        return decorate

    reconcile, wake = register_long_task_reconcile(
        SimpleNamespace(task=task), lambda: runtime.service, resume_task=resume_task
    )
    runtime.service.long_wake = wake

    def scan(tenant_id):
        reconcile.request = SimpleNamespace(headers={"tenant_id": tenant_id})
        reconcile()

    with tenant_execution_scope(7):
        ack = await submit(runtime, target)
        dispatch_id = ack["dispatch_id"]
        reconcile.apply_async.assert_called_once_with(args=[execution_id, CALL], headers={"tenant_id": 7})
    await asyncio.to_thread(scan, None)
    await asyncio.to_thread(scan, 8)
    resume_task.apply_async.assert_not_called()
    await asyncio.to_thread(scan, 7)
    await asyncio.to_thread(scan, 7)
    assert resume_task.apply_async.call_count == 1
    runtime.now[0] += 1
    await asyncio.to_thread(scan, 7)
    assert resume_task.apply_async.call_count == 2
    resume_task.apply_async.assert_called_with(
        args=[execution_id, interaction_id, dispatch_id], headers={"tenant_id": 7}
    )

    with tenant_execution_scope(7):
        dispatch = repo.claim_dispatch(execution_id, dispatch_id)
        assert dispatch is not None
        assert repo.claim_dispatch(execution_id, dispatch_id) is None
    runtime.now[0] += 1
    await asyncio.to_thread(scan, 7)
    assert resume_task.apply_async.call_count == 2
    with tenant_execution_scope(7):
        assert len(repo.get_execution(execution_id)["dispatches"]) == 2
        assert not runtime.outputs


async def test_abandoned_owner_recovers_remote_fact_without_promoting_phase(interaction_runtime, monkeypatch):
    runtime = interaction_runtime
    repo = runtime.repo
    other = PlatformAgentRepository(repo.sessions, clock=repo.clock)
    provider = runtime.service.provider
    target = await waiting(runtime, "lost")
    execution_id = target[0]
    with tenant_execution_scope(7):
        ack = await submit(runtime, target)
        dispatch = repo.claim_dispatch(execution_id, ack["dispatch_id"])
        repo.permit_interaction_submit(dispatch, CALL)
        repo.confirm_interaction_handoff(dispatch, CALL)
        task = repo.long_snapshot(execution_id, CALL)
        interaction = task["interaction"]
        ref = AgentReference.model_validate(task["ref"])
        actor = await runtime.service._long_actor(runtime.user, task)
        form = provider._interaction(task["run_id"])
        with pytest.raises(TimeoutError):
            await provider.submit_interaction(
                actor, ref, task["run_id"], form, interaction["answer"], interaction["remote_key"]
            )
        repo.mark_interaction_unknown(dispatch, CALL)
        receipt = await provider.lookup_submission(actor, ref, task["run_id"], form, interaction["remote_key"])
        assert receipt.status == "ACCEPTED"
        monkeypatch.setattr(provider, "submit_interaction", AsyncMock())

        runtime.now[0] += 1
        assert (execution_id, CALL) in other.due_long_calls(7, interaction_recovery=True)[0]
        stale, expires = repo.claim_interaction_receipt_check(execution_id, CALL, 7)
        runtime.now[0] = expires
        other.finish_interaction_receipt_check(
            execution_id, CALL, stale, receipt.model_copy(update={"status": "REJECTED"})
        )
        await runtime.service.reconcile_long(7, execution_id, CALL)
        recovered = other.long_snapshot(execution_id, CALL)
        assert recovered["interaction"]["remote_receipt"] == "ACCEPTED"
        assert recovered["interaction"]["phase"] == "SUBMIT_UNKNOWN"
        assert recovered["deadline"] == task["deadline"]
        assert other.claim_dispatch(execution_id, ack["dispatch_id"]) is None
        provider.submit_interaction.assert_not_awaited()

        runtime.now[0] = task["deadline"]
        await runtime.service.reconcile_long(7, execution_id, CALL)
        closed = other.long_snapshot(execution_id, CALL)
        assert (closed["local_state"], closed["reason"]) == ("TIMED_OUT", "SUBMIT_UNKNOWN")
        assert closed["interaction"]["remote_receipt"] == "ACCEPTED"
        with pytest.raises(PlatformAgentExecutionError):
            repo.record_interaction_receipt(dispatch, CALL, receipt)
        assert_sealed(closed)
        assert not runtime.outputs

        runtime.now[0] = closed["retain_until"]
        await runtime.service.reconcile_long(7, execution_id, CALL)
        # 取消窗口先结束。随后扫描移除超期去重材料。
        await runtime.service.reconcile_long(7, execution_id, CALL)
        with pytest.raises(PlatformAgentExecutionError):
            await submit(runtime, target)
        assert "answer_digest" not in other.long_snapshot(execution_id, CALL)["interaction"]


async def test_sweep_closes_lost_graph_after_agent_output_without_repeating_it(interaction_runtime):
    runtime = interaction_runtime
    repo = runtime.repo
    target = await waiting(runtime)
    execution_id = target[0]
    with tenant_execution_scope(7):
        ack = await submit(runtime, target)
        dispatch = repo.claim_dispatch(execution_id, ack["dispatch_id"])
        result = await runtime.service.resume_long_interaction(runtime.user, dispatch, CALL)
        assert result
        with repo.output_scope(dispatch, CALL.rsplit(":", 1)[0], 0, runtime.service.config):
            pass
        completed = repo.long_snapshot(execution_id, CALL)
        assert completed["local_state"] == "SUCCEEDED"
        assert_sealed(completed)
        runtime.now[0] = completed["deadline"]
        assert (execution_id, CALL) in repo.due_long_calls(7)[0]
        await runtime.service.reconcile_long(7, execution_id, CALL)
        assert repo.get_execution(execution_id)["state"] == "FAILED"
        assert repo.long_snapshot(execution_id, CALL)["local_state"] == "SUCCEEDED"
        assert repo.claim_dispatch(execution_id, ack["dispatch_id"]) is None
        with pytest.raises(PlatformAgentExecutionError):
            repo.assert_long_graph_live(dispatch)
        assert not runtime.outputs


async def test_sweep_cleans_legacy_terminal_record_without_extending_its_receipt_window(interaction_runtime):
    runtime = interaction_runtime
    repo = runtime.repo
    target = await waiting(runtime)
    execution_id = target[0]
    with tenant_execution_scope(7):
        ack = await submit(runtime, target)
        calls = repo.get_execution(execution_id)["calls"]
        call = calls[CALL]
        task = call["long_task"]
        task.update(local_state="STOPPED", reason="LOCAL_STOP", retain_until=repo.clock() + 24 * 60 * 60)
        task["interaction"]["phase"] = "SUBMIT_UNKNOWN"
        call["state"] = "ABANDONED"
        with repo.transaction() as session:
            row = session.get(PlatformAgentExecution, execution_id)
            row.calls = calls
            row.state = "ABORTED"
        runtime.now[0] += 20
        assert (execution_id, CALL) in repo.due_long_calls(7, interaction_recovery=True)[0]
        await runtime.service.reconcile_long(7, execution_id, CALL)
        closed = repo.long_snapshot(execution_id, CALL)
        assert_sealed(closed)
        assert closed["interaction"]["receipt_until"] < repo.clock()
        assert (await submit(runtime, target))["dispatch_id"] == ack["dispatch_id"]
