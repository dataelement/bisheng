from asyncio import create_task, to_thread, wait_for
from threading import Event
from types import SimpleNamespace

import pytest

from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.worker.workflow import kunlian_workflow_run as worker
from bisheng.workflow.domain.schemas.kunlian_workflow_invocation import RunError
from bisheng.workflow.graph.graph_engine import GraphEngine
from bisheng.workflow.nodes.input.input import InputNode
from bisheng.workflow.nodes.start.start import StartNode
from test.workflow.kunlian_interaction_worker import fake_node_services
from test.workflow.test_kunlian_workflow_interaction import interactive
from test.workflow.test_kunlian_workflow_invocation import request
from test.workflow.test_kunlian_workflow_publication import SCOPE
from test.workflow.test_kunlian_workflow_run_control_cancel import OWNER, kinds
from test.workflow.test_kunlian_workflow_run_control_cancel import control_store as control_store


@pytest.mark.parametrize("phase", ["initial", "resume", "resume_load", "wait_write"])
async def test_running_worker_stops_at_next_boundary(control_store, monkeypatch, phase):
    runs, _ = control_store
    starts = fake_node_services(monkeypatch.setattr)
    row, _ = runs.admit(
        SCOPE, OWNER.user_id, "start", request(question="V1") if phase == "initial" else interactive(), run_control=True
    )

    async def authorize(record):
        assert get_current_tenant_id() == record.tenant_id == 7
        return SimpleNamespace(tenant_id=7, user_id=12)

    service = SimpleNamespace(repository=runs, authorize_run=authorize)
    interaction_id = None
    if phase.startswith("resume"):
        await worker.execute_run(service, 7, row.session_id)
        waiting = runs.load(7, row.session_id)
        interaction_id = waiting.material["interaction_id"]
        runs.answer(OWNER, row.session_id, interaction_id, "answer", {"question": "resume"})

    entered, release = Event(), Event()
    target, method = {
        "initial": (StartNode, "_run"),
        "resume": (InputNode, "_run"),
        "resume_load": (worker, "resume_graph"),
        "wait_write": (runs, "wait_for_input"),
    }[phase]
    original = getattr(target, method)

    def hold(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(target, method, hold)
    if phase == "resume_load":

        def restore_unexpected(*_):
            pytest.fail("取消后仍装载等待点")

        monkeypatch.setattr(worker, "restore_wait", restore_unexpected)
    outputs = []
    original_output = worker.ResultCallback.on_output_msg

    def output(self, data):
        outputs.append(data.node_id)
        return original_output(self, data)

    monkeypatch.setattr(worker.ResultCallback, "on_output_msg", output)
    execution = create_task(worker.execute_run(service, 7, row.session_id, interaction_id))
    try:
        assert await to_thread(entered.wait, 5)
        assert runs.request_cancel(OWNER, row.session_id).status == "CANCEL_REQUESTED"
    finally:
        release.set()
        await wait_for(execution, 5)
    result = runs.load(7, row.session_id)
    assert result.status == "CANCELLED" and result.output is None
    assert kinds(result)[-2:] == ["CANCEL_ACCEPTED", "CANCELLED"]
    assert outputs == [] and starts == [12]


async def test_async_graph_checks_entry_and_leaves_unconfigured_graph_alone(control_store, monkeypatch):
    runs, _ = control_store
    row, _ = runs.admit(SCOPE, OWNER.user_id, "async", request(question="fixture"))
    graph = row.material["graph"]
    fake_node_services(monkeypatch.setattr)
    calls = []

    def stop():
        raise RunError("CONTROL_STOPPED")

    async def run(state):
        calls.append(state)

    node = SimpleNamespace(arun=run)
    configured = GraphEngine(async_mode=True, workflow_data=graph, node_entry_check=stop)
    with pytest.raises(RunError, match="CONTROL_STOPPED"):
        await configured._node_runner(node)({"blocked": True})
    legacy = GraphEngine(async_mode=True, workflow_data=graph)
    await legacy._node_runner(node)({"legacy": True})
    assert calls == [{"legacy": True}]
