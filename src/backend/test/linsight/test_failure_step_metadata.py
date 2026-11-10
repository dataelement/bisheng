"""Task failures preserve source across streaming and storage."""

import ast
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from langchain_core.messages import ToolMessage

from bisheng.linsight.domain.services.stream_event_mapper import StreamEventMapper

FAILURE = {
    "version": 1,
    "failure_id": "failure-1",
    "category": "database",
    "service": "milvus",
    "occurred_at": "2026-11-05T10:00:00+08:00",
}


def test_soft_failure_source_and_namespace_coexist_in_end_frame():
    mapper = StreamEventMapper("sv")
    start = mapper._handle_tool_starts(
        [{"id": "c", "name": "search_knowledge_base", "args": {"knowledge_id": 7, "knowledge_name": "invented"}}],
        "research:1",
    )[0]
    end = mapper._handle_tool_end(
        ToolMessage(content=json.dumps({"error": "search failed", "failure_info": FAILURE}), tool_call_id="c"),
        "c",
        "research:1",
    )[0]
    assert end.extra_info["failure_info"] == FAILURE
    assert end.call_id == start.call_id
    assert end.extra_info["namespace"] == "research:1"


def test_arbitrary_error_text_does_not_fabricate_failure_category():
    mapper = StreamEventMapper("sv")
    mapper._handle_tool_starts([{"id": "c", "name": "search_knowledge_base", "args": {}}], None)
    end = mapper._handle_tool_end(ToolMessage(content="database timeout", tool_call_id="c"), "c", None)[0]
    assert "failure_info" not in end.extra_info


def test_degraded_model_step_keeps_source_and_namespace():
    from langchain_core.messages import AIMessage

    mapper = StreamEventMapper("sv")
    events = mapper._handle_messages(
        (AIMessage(content="Skipped", additional_kwargs={"failure_info": FAILURE}), {}), "research:1"
    )
    assert events[0].extra_info["failure_info"] == FAILURE
    assert events[0].extra_info["namespace"] == "research:1"
    assert events[0].step_type == "tool"


def _production_method(path, cls_name, name, namespace):
    path = Path(__file__).resolve().parents[2] / "bisheng" / path
    tree = ast.parse(path.read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls_name)
    method = next(n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    module = ast.fix_missing_locations(ast.Module(body=[future, method], type_ignores=[]))
    exec(compile(module, str(path), "exec"), namespace)
    return namespace[name]


async def test_failure_preserves_answer_files_recovery_and_public_source():
    from bisheng.common.services.failure_context import FailureContextAdapter
    from bisheng.common.services.llm_error_classifier import ErrorType, classify_for_event

    error = RuntimeError("password=secret https://internal.example")
    info = FailureContextAdapter.capture(error, category="database", service="redis")
    session = SimpleNamespace(
        id="sv", user_id=1, output_result={"answer": "partial", "files": [{"name": "ok.pdf"}], "attempt_id": "a1"}
    )
    state = SimpleNamespace(set_session_version_info=AsyncMock(), push_message=AsyncMock())
    task = SimpleNamespace(_state_manager=state, _terminate_unfinished_tasks=AsyncMock())
    namespace = {
        "FailureContextAdapter": FailureContextAdapter,
        "classify_for_event": classify_for_event,
        "ErrorType": ErrorType,
        "SessionVersionStatusEnum": SimpleNamespace(FAILED="failed"),
        "linsight_execute_utils": SimpleNamespace(persist_task_turn_message=AsyncMock()),
        "settings": SimpleNamespace(aget_all_config=AsyncMock(return_value={})),
        "MessageData": SimpleNamespace,
        "MessageEventType": SimpleNamespace(ERROR_MESSAGE="error_message"),
    }
    method = _production_method(
        "linsight/domain/task_exec.py", "LinsightWorkflowTask", "_handle_task_failure", namespace
    )
    await method(task, session, "Failed", exc=error)
    assert session.output_result["answer"] == "partial"
    assert session.output_result["files"] == [{"name": "ok.pdf"}]
    assert session.output_result["attempt_id"] == "a1"
    assert session.output_result["failure_info"] == info
    payload = state.push_message.call_args.args[0].data
    assert payload["failure_info"] == info
    assert "secret" not in str(payload)
    assert "internal.example" not in str(session.output_result)


def test_public_task_history_sanitizes_legacy_error_fields_without_touching_answer():
    row = {
        "pending_files": [{"url": "secret"}],
        "output_result": {
            "answer": "partial",
            "detail": "password=secret",
            "exception": "https://internal",
            "failure_info": FAILURE,
        },
    }
    method = _production_method(
        "linsight/domain/models/linsight_session_version.py",
        "LinsightSessionVersion",
        "public_dump",
        {
            "FailureContextAdapter": __import__(
                "bisheng.common.services.failure_context", fromlist=["FailureContextAdapter"]
            ).FailureContextAdapter
        },
    )
    public = method(SimpleNamespace(model_dump=lambda: row))["output_result"]
    assert public["answer"] == "partial"
    assert public["failure_info"] == FAILURE
    assert "secret" not in str(public)
    assert "https://internal" not in str(public)
