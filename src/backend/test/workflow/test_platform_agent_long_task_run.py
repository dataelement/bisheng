from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.flow import PlatformAgentExecutionError, PlatformAgentOutputError, PlatformAgentUnknownError
from bisheng.core.config.settings import PlatformAgentConf
from bisheng.workflow.domain.schemas.platform_agent import VerifiedAgentActor
from bisheng.workflow.domain.services import platform_agent_service as domain
from test.workflow.test_platform_agent_long_task_contract import long_remote as long_remote
from test.workflow.test_platform_agent_node import node_data


@pytest.fixture
def long_run(long_agent_store, long_remote, monkeypatch):
    repo, _, _, now = long_agent_store
    provider = long_remote.provider()
    provider.clock = repo.clock
    monkeypatch.setattr(domain, "require_business_action", AsyncMock())

    async def advance(delay):
        now[0] += delay

    service = domain.PlatformAgentService(
        config=PlatformAgentConf(), repository=repo, provider=provider, long_pause=advance, enable_long_tasks=True
    )
    node = node_data()
    node["group_params"][0]["params"].append({"key": "execution_mode", "value": "async"})
    row, dispatch_id = repo.prepare_execution(
        "f" * 32, "long-session", VerifiedAgentActor(12, 7), {"nodes": [{"data": node}]}, service.config, "DEBUG"
    )
    dispatch = repo.claim_dispatch(row["execution_id"], dispatch_id)
    return SimpleNamespace(
        repo=repo,
        provider=provider,
        ledger=long_remote.ledger,
        now=now,
        service=service,
        node=node,
        dispatch=dispatch,
        user=SimpleNamespace(user_id=12, tenant_id=7),
    )


async def test_lost_acceptance_polls_original_run_and_commits_one_output(long_run, monkeypatch):
    run = long_run
    start = run.provider.start

    async def lost(*args):
        await start(*args)
        raise TimeoutError

    monkeypatch.setattr(run.provider, "start", AsyncMock(side_effect=lost))
    call = (run.user, "f" * 32, run.dispatch, run.node, 0, lambda _: "value")
    assert (await run.service.invoke_node(*call))["answer"] == "hello"
    with run.repo.output_scope(run.dispatch, run.node["id"], 0, run.service.config):
        pass
    with pytest.raises(PlatformAgentExecutionError):
        await run.service.invoke_node(*call)
    assert run.provider.start.await_count == 1
    record = run.repo.get_execution(run.dispatch.execution_id)["calls"][f"{run.node['id']}:0"]
    assert record["long_task"]["local_state"] == "SUCCEEDED"
    assert record["long_task"]["remote_state"] == "SUCCEEDED"


async def test_invalid_result_never_enters_output_scope(long_run, monkeypatch):
    run = long_run
    get_result = run.provider.get_result

    async def wrong(*args):
        result = await get_result(*args)
        return result.model_copy(update={"agent_run_id": "another-run"})

    monkeypatch.setattr(run.provider, "get_result", wrong)
    with pytest.raises(PlatformAgentOutputError):
        await run.service.invoke_node(run.user, "f" * 32, run.dispatch, run.node, 0, lambda _: None)
    with pytest.raises(PlatformAgentExecutionError):
        with run.repo.output_scope(run.dispatch, run.node["id"], 0, run.service.config):
            pytest.fail("不匹配的结果获得了输出许可")


@pytest.mark.parametrize("before_result_ready", [True, False])
async def test_output_deadline_persists_timeout_even_if_remote_succeeded(long_run, monkeypatch, before_result_ready):
    run = long_run
    key = f"{run.node['id']}:0"
    deadline = run.now[0] + 30
    call = (run.user, "f" * 32, run.dispatch, run.node, 0, lambda _: "value")
    if before_result_ready:
        ready = run.repo.ready_long_output

        def ready_after_deadline(*args):
            run.now[0] = deadline
            ready(*args)

        monkeypatch.setattr(run.repo, "ready_long_output", ready_after_deadline)
        with pytest.raises(PlatformAgentUnknownError):
            await run.service.invoke_node(*call)
    else:
        await run.service.invoke_node(*call)
        run.now[0] = deadline
        with pytest.raises(PlatformAgentUnknownError):
            with run.repo.output_scope(run.dispatch, run.node["id"], 0, run.service.config):
                pytest.fail("截止后仍允许写入输出")
    task = run.repo.long_snapshot(run.dispatch.execution_id, key)
    assert (task["local_state"], task["remote_state"], task["reason"], task["cancel_state"]) == (
        "TIMED_OUT",
        "SUCCEEDED",
        "RESULT_UNAVAILABLE",
        "NO_ACTION",
    )


async def test_status_summary_distinguishes_sequential_nodes_after_json_reordering(long_run):
    run = long_run
    first = {**run.node, "id": "z-first"}
    second = {**run.node, "id": "a-second"}
    await run.service.invoke_node(run.user, "f" * 32, run.dispatch, first, 0, lambda _: "value")
    with run.repo.output_scope(run.dispatch, first["id"], 0, run.service.config):
        pass
    await run.service.invoke_node(run.user, "f" * 32, run.dispatch, second, 0, lambda _: "value")
    record = run.repo.get_execution(run.dispatch.execution_id)
    record["calls"] = dict(sorted(record["calls"].items()))
    previous = run.service.long_summary(record, "z-first:0")
    latest = run.service.long_summary(record)
    assert latest["call_sequence"] > previous["call_sequence"]
    assert latest["local_state"] == "WAITING_RESULT"
    assert latest["agent_run_id"] != previous["agent_run_id"]


async def test_timeout_before_sending_records_not_sent_and_never_calls_provider(long_run, monkeypatch):
    run = long_run
    monkeypatch.setattr(run.service, "_long_actor", AsyncMock(side_effect=TimeoutError))
    monkeypatch.setattr(run.provider, "start", AsyncMock())
    with pytest.raises(PlatformAgentExecutionError):
        await run.service.invoke_node(run.user, "f" * 32, run.dispatch, run.node, 0, lambda _: None)
    run.provider.start.assert_not_awaited()
    saved = run.repo.long_snapshot(run.dispatch.execution_id, f"{run.node['id']}:0")
    assert (saved["local_state"], saved["remote_state"], saved["reason"], saved["cancel_state"]) == (
        "TIMED_OUT",
        "NOT_SENT",
        "START_TIMEOUT",
        "NO_ACTION",
    )
