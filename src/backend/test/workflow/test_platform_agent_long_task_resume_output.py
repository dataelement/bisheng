import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import select

from bisheng.common.errcode.flow import PlatformAgentExecutionError, PlatformAgentPermissionError
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.database.models.message import ChatMessage
from bisheng.worker.workflow import platform_agent_long_task_resume as resume_worker
from bisheng.worker.workflow import tasks
from bisheng.worker.workflow.redis_callback import LongTaskResumeOutput
from bisheng.workflow.application import platform_agent
from bisheng.workflow.callback.event import OutputMsgData
from test.workflow.test_platform_agent_interaction_wait import FLOW_ID, SESSION
from test.workflow.test_platform_agent_long_task_resume_reconcile import read, start
from test.workflow.test_platform_agent_long_task_resume_reconcile import runtime as runtime
from test.workflow.test_platform_agent_long_task_resume_wait import CALL
from test.workflow.test_platform_agent_long_task_resume_wait import interaction_runtime as interaction_runtime
from test.workflow.test_platform_agent_long_task_resume_wait import long_remote as long_remote

MESSAGE = {"name": "输出", "unique_id": "out", "node_id": "output_example", "msg": "恢复后的文本", "output_key": ""}


async def ready(run, monkeypatch):
    execution_id, _ = await start(run, monkeypatch)
    with tenant_execution_scope(7):
        with run.repo.transaction() as db:
            ChatMessage.__table__.create(db.get_bind())
        for tick in (1003, 1004):
            run.now[0] = tick
            await run.service.reconcile_long(7, execution_id, CALL)
        row, _, resume = read(run, execution_id)
    assert row["state"] == "WAITING" and resume["phase"] == "RESUME_READY"
    return execution_id, resume["dispatch_id"]


def messages(run):
    with run.repo.transaction() as db:
        return [m.model_dump() for m in db.exec(select(ChatMessage)).all()]


@pytest.mark.parametrize("interruption", ["before_commit", "after_flush"])
async def test_expired_owner_can_be_replaced_and_output_commits_once(runtime, monkeypatch, interruption):
    execution_id, dispatch_id = await ready(runtime, monkeypatch)
    with tenant_execution_scope(7):
        original = await platform_agent.claim_long_task_resume(execution_id, CALL, dispatch_id)
        assert await platform_agent.claim_long_task_resume(execution_id, CALL, dispatch_id) is None
        staged = LongTaskResumeOutput()
        staged.on_output_msg(OutputMsgData(**MESSAGE))
        assert staged.message == MESSAGE and not messages(runtime)
        if interruption == "after_flush":
            from bisheng.chat_session.application import workflow_output

            insert = workflow_output.write_output

            def abort_after_flush(*args, **kwargs):
                assert insert(*args, **kwargs) > 0
                raise SQLAlchemyError("fixture rollback")

            with monkeypatch.context() as patch:
                patch.setattr(workflow_output, "write_output", abort_after_flush)
                with pytest.raises(PlatformAgentExecutionError):
                    await platform_agent.commit_long_task_resume_output(original, MESSAGE)
        row, _, resume = read(runtime, execution_id)
        assert row["state"] == "RUNNING" and resume["phase"] == "RESUMING" and not messages(runtime)
        runtime.now[0] = row["dispatches"][dispatch_id]["lease_until"]
        replacement = await platform_agent.claim_long_task_resume(execution_id, CALL, dispatch_id)
        assert replacement["dispatch"].owner != original["dispatch"].owner
        assert not runtime.repo.fail_long_task_resume(original["dispatch"], CALL, "RUN_FAILED")
        with pytest.raises(PlatformAgentExecutionError):
            await platform_agent.commit_long_task_resume_output(original, MESSAGE)
        message_id = await platform_agent.commit_long_task_resume_output(replacement, MESSAGE)
        assert await platform_agent.claim_long_task_resume(execution_id, CALL, dispatch_id) is None
        result = await platform_agent.BrowserPlatformAgentRuntime(runtime.repo).read_long_task_resume_output(
            runtime.user, FLOW_ID, SESSION, execution_id
        )
        with pytest.raises(PlatformAgentPermissionError):
            await platform_agent.BrowserPlatformAgentRuntime(runtime.repo).read_long_task_resume_output(
                runtime.publisher, FLOW_ID, SESSION, execution_id
            )
        row, call, resume = read(runtime, execution_id)
        records = messages(runtime)
    assert len(records) == 1 and records[0]["id"] == result["message_id"] == message_id
    assert records[0]["tenant_id"] == 7 and json.loads(records[0]["extra"]) == {
        "workflow_long_task_resume": {"format": 1, "execution_id": execution_id}
    }
    assert result["message"] == MESSAGE
    assert row["state"] == call["state"] == "SUCCEEDED" and row["dispatches"][dispatch_id]["state"] == "DONE"
    assert resume["phase"] == "TERMINAL" and resume["message_id"] == message_id
    assert "snapshot" not in resume and "result" not in resume


@pytest.mark.parametrize("failure", ["bad_snapshot", "revoked"])
async def test_resume_failure_closes_only_original_attempt_without_message(runtime, monkeypatch, failure):
    execution_id, dispatch_id = await ready(runtime, monkeypatch)
    monkeypatch.setattr(
        resume_worker, "settings", SimpleNamespace(get_workflow_conf=lambda: SimpleNamespace(max_steps=12, timeout=2))
    )
    restore = Mock(wraps=resume_worker.restore_long_task_wait)
    monkeypatch.setattr(resume_worker, "restore_long_task_wait", restore)
    if failure == "bad_snapshot":
        with runtime.repo._long_scope(execution_id, CALL) as (_, _, task, _):
            task["resume"]["snapshot"]["graph_digest"] = "invalid"
    else:
        monkeypatch.setattr(runtime.service, "_long_actor", AsyncMock(side_effect=UnAuthorizedError))
    app = SimpleNamespace(task=lambda **_options: lambda func: func)
    resume_task = tasks.register_long_task_resume(app)
    resume_task.request = SimpleNamespace(headers={"tenant_id": 7})
    await asyncio.to_thread(resume_task, execution_id, CALL, dispatch_id)
    assert restore.call_count == (1 if failure == "bad_snapshot" else 0)
    with tenant_execution_scope(7):
        row, call, resume = read(runtime, execution_id)
        assert row["state"] == "FAILED" and resume["phase"] == "TERMINAL"
        assert call["long_task"]["reason"] == ("RESUME_STATE_INVALID" if failure == "bad_snapshot" else "FORBIDDEN")
        assert not messages(runtime)
