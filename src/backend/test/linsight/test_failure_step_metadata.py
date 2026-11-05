"""Task failures and verified knowledge targets survive streaming and storage."""

import ast
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from langchain_core.messages import AIMessageChunk, ToolMessage

from bisheng.linsight.domain.services.stream_event_mapper import StreamEventMapper

TARGET = {"version": 1, "knowledge_id": "7", "kind": "space", "name": "Policies"}
FAILURE = {
    "version": 1,
    "failure_id": "failure-1",
    "category": "database",
    "service": "milvus",
    "occurred_at": "2026-11-05T10:00:00+08:00",
}


def test_verified_target_and_soft_failure_coexist_in_end_frame():
    mapper = StreamEventMapper("sv", knowledge_targets={"7": TARGET})
    start = mapper._handle_tool_starts(
        [{"id": "c", "name": "search_knowledge_base", "args": {"knowledge_id": 7, "knowledge_name": "invented"}}],
        "research:1",
    )[0]
    end = mapper._handle_tool_end(
        ToolMessage(content=json.dumps({"error": "search failed", "failure_info": FAILURE}), tool_call_id="c"),
        "c",
        "research:1",
    )[0]
    assert start.extra_info["knowledge_target"] == TARGET
    assert end.extra_info["knowledge_target"] == TARGET
    assert end.extra_info["failure_info"] == FAILURE
    assert end.call_id == start.call_id
    assert end.extra_info["namespace"] == "research:1"


def test_partial_args_enrich_once_and_freeze_target():
    targets = {"7": dict(TARGET)}
    mapper = StreamEventMapper("sv", knowledge_targets=targets)
    start = mapper._handle_tool_starts([{"id": "c", "name": "search_knowledge_base", "args": {}}], None)[0]
    assert "knowledge_target" not in start.extra_info
    chunk = AIMessageChunk(
        content="", tool_call_chunks=[{"id": "c", "index": 0, "name": None, "args": '{"knowledge_id":7}'}]
    )
    events = mapper._handle_messages((chunk, {}), None)
    assert len(events) == 1
    assert events[0].call_id == start.call_id
    assert events[0].extra_info["knowledge_target"] == TARGET
    assert mapper._handle_messages((AIMessageChunk(content=""), {}), None) == []
    targets["7"]["name"] = "renamed"
    end = mapper._handle_tool_end(ToolMessage(content="ok", tool_call_id="c"), "c", None)[0]
    assert end.extra_info["knowledge_target"] == TARGET


def test_orphan_end_and_unverified_ids_never_invent_names():
    mapper = StreamEventMapper("sv", knowledge_targets={"7": TARGET})
    mapper._handle_tool_end(ToolMessage(content="ok", tool_call_id="orphan"), "orphan", None)
    events = mapper._handle_tool_starts(
        [{"id": "orphan", "name": "search_knowledge_base", "args": {"knowledge_id": "7"}}], None
    )
    assert all(e.extra_info["knowledge_target"] == TARGET for e in events)
    missing = mapper._handle_tool_starts(
        [{"id": "bad", "name": "search_knowledge_base", "args": {"knowledge_id": 8, "knowledge_name": "Secret"}}], None
    )[0]
    assert "knowledge_target" not in missing.extra_info


def test_arbitrary_error_text_does_not_fabricate_failure_category():
    mapper = StreamEventMapper("sv")
    mapper._handle_tool_starts([{"id": "c", "name": "search_knowledge_base", "args": {}}], None)
    end = mapper._handle_tool_end(ToolMessage(content="database timeout", tool_call_id="c"), "c", None)[0]
    assert "failure_info" not in end.extra_info


def test_parallel_namespaces_with_reused_provider_id_keep_own_targets():
    other = {**TARGET, "knowledge_id": "8", "name": "Other"}
    mapper = StreamEventMapper("sv", knowledge_targets={"7": TARGET, "8": other})
    first = mapper._handle_tool_starts(
        [{"id": "c", "name": "search_knowledge_base", "args": {"knowledge_id": 7}}], "a"
    )[0]
    second = mapper._handle_tool_starts(
        [{"id": "c", "name": "search_knowledge_base", "args": {"knowledge_id": 8}}], "b"
    )[0]
    end_a = mapper._handle_tool_end(ToolMessage(content="ok", tool_call_id="c"), "c", "a")[0]
    end_b = mapper._handle_tool_end(ToolMessage(content="ok", tool_call_id="c"), "c", "b")[0]
    assert end_a.call_id == first.call_id and end_b.call_id == second.call_id
    assert end_a.extra_info["knowledge_target"] == TARGET
    assert end_b.extra_info["knowledge_target"] == other


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
    from bisheng.common.services.llm_error_classifier import classify_for_event

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
        "SessionVersionStatusEnum": SimpleNamespace(FAILED="failed"),
        "linsight_execute_utils": SimpleNamespace(persist_task_turn_message=AsyncMock()),
        "settings": SimpleNamespace(aget_all_config=AsyncMock(return_value={})),
        "MessageData": SimpleNamespace,
        "MessageEventType": SimpleNamespace(ERROR_MESSAGE="error_message"),
    }
    method = _production_method(
        "linsight/domain/task_exec.py", "LinsightWorkflowTask", "_handle_task_failure", namespace
    )
    await method(task, session, "Failed", exc=error, extra_payload={"recovery_status": "available"})
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
        "linsight/domain/models/linsight_session_version.py", "LinsightSessionVersion", "public_dump", {}
    )
    public = method(SimpleNamespace(model_dump=lambda: row))["output_result"]
    assert public["answer"] == "partial"
    assert public["failure_info"] == FAILURE
    assert "secret" not in str(public)
    assert "https://internal" not in str(public)
