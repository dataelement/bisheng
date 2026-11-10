import asyncio
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.database.models.flow_version import FlowVersion
from bisheng.workflow.domain.models.platform_agent_execution import PlatformAgentExecution
from test.workflow.test_platform_agent_interaction_submit import CALL
from test.workflow.test_platform_agent_interaction_wait import (
    AGENT_ID,
    FLOW_ID,
    prepare,
    sample_graph,
)
from test.workflow.test_platform_agent_interaction_wait import (
    interaction_runtime as interaction_runtime,
)
from test.workflow.test_platform_agent_interaction_wait import (
    long_remote as long_remote,
)


@pytest.mark.parametrize("scenario", ["success", "revoked", "bad_checkpoint"])
async def test_worker_process_restores_same_execution_after_original_exits(interaction_runtime, tmp_path, scenario):
    runtime = interaction_runtime
    backend = Path(__file__).resolve().parents[2]
    remote_path = tmp_path / "agent-mock.sqlite3"
    with runtime.repo.transaction() as db:
        database = db.get_bind().url.database

    async def run_process(envelope):
        completed = await asyncio.to_thread(
            subprocess.run,
            [
                sys.executable,
                "-m",
                "test.workflow.platform_agent_interaction_worker",
                database,
                str(remote_path),
                json.dumps({"clock": runtime.now[0], "headers": {"tenant_id": 7}, **envelope}),
            ],
            cwd=backend,
            capture_output=True,
            text=True,
            timeout=45,
        )
        assert completed.returncode == 0, (completed.stderr[-3000:], completed.stdout[-2000:])
        return json.loads(completed.stdout.splitlines()[-1])

    graph = sample_graph("lost")
    output = graph["nodes"][2]["data"]["group_params"][0]["params"]
    next(p for p in output if p["key"] == "message")["value"]["msg"] += " {{#start_example.user_info#}}"
    with tenant_execution_scope(7):
        execution, initial = await prepare(runtime, graph)
    execution_id = execution["execution_id"]
    first = await run_process({"phase": "START", "execution_id": execution_id, "dispatch_id": initial})
    assert first["state"] == "WAITING" and first["error"] is None
    assert first["calls"] == [["start", "lost"]] and first["nodes"] == ["start_example"] and not first["outputs"]
    with tenant_execution_scope(7):
        before = runtime.repo.long_snapshot(execution_id, CALL)
        interaction = before["interaction"]
        assert interaction["snapshot"]["workflow_version_id"] == 1
        current_graph = sample_graph("v2")
        with runtime.repo.transaction() as db:
            db.add(FlowVersion(id=2, flow_id=FLOW_ID, name="v2", tenant_id=7, user_id=11, data=current_graph))
        await runtime.service.publish(runtime.publisher, FLOW_ID, 2)
        accepted = await runtime.service.submit_interaction_answer(
            runtime.user,
            execution_id,
            CALL,
            interaction["interaction_id"],
            interaction["form"]["revision"],
            "browser-submission",
            "联调答案",
        )
        if scenario == "bad_checkpoint":
            with runtime.repo.transaction() as db:
                row = db.get(PlatformAgentExecution, execution_id)
                calls = deepcopy(row.calls)
                calls[CALL]["long_task"]["interaction"]["snapshot"]["graph_digest"] = "wrong"
                row.calls = calls
    envelope = {
        "phase": "RESUME",
        "execution_id": execution_id,
        "interaction_id": interaction["interaction_id"],
        "dispatch_id": accepted["dispatch_id"],
        "revoked": scenario == "revoked",
    }
    second = await run_process(envelope)
    assert second["pid"] != first["pid"]
    assert "start_example" not in second["nodes"]
    if scenario == "success":
        assert second["error"] is None and second["state"] == "SUCCEEDED"
        assert second["calls"] == [["submit", "lost"]]
        assert second["nodes"].count(AGENT_ID) == len(second["outputs"]) == 1
        assert f"prefix-{first['pid']}" in second["outputs"][0] and "联调答案" in second["outputs"][0]
        duplicate = await run_process(envelope)
        assert duplicate["error"] is None and duplicate["calls"] == duplicate["outputs"] == []
    else:
        assert second["state"] == "FAILED" and second["error"]
        assert second["calls"] == second["outputs"] == []
    with tenant_execution_scope(7):
        after = runtime.repo.long_snapshot(execution_id, CALL)
        stored = runtime.repo.get_execution(execution_id)
        if scenario == "success":
            replay = await runtime.service.submit_interaction_answer(
                runtime.user,
                execution_id,
                CALL,
                interaction["interaction_id"],
                interaction["form"]["revision"],
                "browser-submission",
                "联调答案",
            )
            assert replay["dispatch_id"] == accepted["dispatch_id"]
            assert after["local_state"] == "SUCCEEDED" and "answer" not in after["interaction"]
    assert after["run_id"] == before["run_id"] and after["ref"] == before["ref"]
    assert after["interaction"]["interaction_id"] == interaction["interaction_id"]
    assert stored["dispatches"][initial]["workflow_version_id"] == 1
    assert {"answer", "form", "snapshot"}.isdisjoint(after["interaction"])
