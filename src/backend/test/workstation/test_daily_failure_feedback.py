"""Execute real daily boundaries with isolated infrastructure dependencies.

The AST loader avoids application startup and the root conftest's worker imports;
only external collaborators are replaced. The function bodies are production code.
"""

import ast
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.documents import Document
from langchain_core.messages import ToolMessage
from loguru import logger
from redis.exceptions import ConnectionError as RedisConnectionError
from starlette.responses import StreamingResponse

ROOT = Path(__file__).resolve().parents[2] / "bisheng"
SECRET = "redis://:private-password@internal-host:6379/0"


def _load(path, names, namespace):
    tree = ast.parse((ROOT / path).read_text())
    nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    module = ast.fix_missing_locations(ast.Module(body=[future, *nodes], type_ignores=[]))
    exec(compile(module, str(ROOT / path), "exec"), namespace)
    return SimpleNamespace(**{name: namespace[name] for name in names})


def _namespace():
    from bisheng.common.utils.think_tags import ThinkBlockStreamFilter

    namespace = {"json": json, "logger": logger, "ThinkBlockStreamFilter": ThinkBlockStreamFilter}
    # Before the production adapter exists, old bodies execute without it.
    try:
        from bisheng.common.services.failure_context import FailureContextAdapter
    except ModuleNotFoundError:
        return namespace
    namespace["FailureContextAdapter"] = FailureContextAdapter
    return namespace


def _chat(names, namespace=None):
    return _load("workstation/domain/services/chat_service.py", names, namespace or _namespace())


def _method(path, cls_name, name, namespace):
    tree = ast.parse((ROOT / path).read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls_name)
    method = next(n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    method.decorator_list = []
    module = ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[]))
    exec(compile(module, str(ROOT / path), "exec"), namespace)
    return namespace[name]


def test_daily_tool_error_is_safe_structured_soft_failure():
    chat = _chat({"_handle_agent_tool_error", "_extract_tool_error", "_parse_tool_results", "_json_safe"})
    content = chat._handle_agent_tool_error(RedisConnectionError(SECRET))
    assert SECRET not in content
    payload = json.loads(content)
    assert payload["failure_info"]["category"] == "database"
    message = ToolMessage(content=content, status="error", tool_call_id="one")
    assert chat._extract_tool_error(message) == payload["error"]


async def test_partial_knowledge_failure_preserves_docs_and_safe_source():
    namespace = _namespace()
    vectorstore = {"milvus": object(), "es": None, "knowledge": SimpleNamespace(name="visible")}
    namespace.update(
        KnowledgeRag=SimpleNamespace(
            get_multi_knowledge_vectorstore=AsyncMock(side_effect=[RedisConnectionError(SECRET), {2: vectorstore}])
        ),
        MultiRetriever=MagicMock(),
        UseKnowledgeBaseParam=object,
        UserPayload=object,
    )
    doc = Document(page_content="useful answer", metadata={"source": "public.pdf"})
    namespace["KnowledgeRetrieverTool"] = MagicMock(return_value=SimpleNamespace(ainvoke=AsyncMock(return_value=[doc])))
    cls = SimpleNamespace(
        _filter_visible_space_kb_ids=AsyncMock(return_value={"space_kb_ids": [], "org_kb_ids": [1, 2]}),
        _post_filter_kb_docs_by_view_file=AsyncMock(return_value=[doc]),
    )
    method = _method(
        "workstation/domain/services/workstation_service.py", "WorkStationService", "queryChunksFromDB", namespace
    )
    user = SimpleNamespace(user_id=7, is_admin=lambda: True)
    formatted, docs, failures = await method(
        cls,
        "policy",
        SimpleNamespace(organization_knowledge_ids=[1, 2], knowledge_space_ids=[], knowledge_space_tag_filters={}),
        1000,
        user,
    )
    assert docs == [doc]
    assert "useful answer" in formatted[0]
    assert failures[0]["failure_info"]["category"] == "database"
    assert SECRET not in json.dumps(failures)


async def test_task_knowledge_technical_failure_remains_soft_but_not_no_hit():
    method = _method("tool/domain/langchain/linsight_knowledge.py", "SearchKnowledgeBase", "_arun", _namespace())
    tool = SimpleNamespace(
        allowed_knowledge_ids=None, search_knowledge=AsyncMock(side_effect=RedisConnectionError(SECRET))
    )
    result = json.loads(await method(tool, "policy", "101"))
    assert result["状态"] == "失败"
    assert result["failure_info"]["category"] == "database"
    assert SECRET not in json.dumps(result)


def test_daily_history_sanitizes_old_provider_errors_and_keeps_partial_answer():
    namespace = _namespace()
    namespace["_message_base_fields"] = lambda row: {"id": row.id}
    helpers = _load(
        "workstation/domain/services/chat_helpers.py",
        {"_format_new_message", "_normalise_agent_message_content"},
        namespace,
    )
    secret = "password=secret https://internal"
    row = SimpleNamespace(
        id=1,
        category="agent_answer",
        type="end",
        extra=json.dumps({"error": True, "error_msg": secret, "detail": secret, "error_code": 12045}),
        message=json.dumps(
            {"msg": "partial answer", "events": [{"type": "tool_call", "error": secret, "results": secret}]}
        ),
    )
    public = helpers._format_new_message(row)
    assert "secret" not in json.dumps(public)
    assert public["message"]["msg"] == "partial answer"
    assert public["extra"]["error_code"] == 12045


@pytest.mark.parametrize("wrapped", [False, True])
async def test_unified_task_submit_failure_preserves_source_in_sse(monkeypatch, wrapped):
    import sys
    from types import ModuleType

    from bisheng.common.errcode.base import BaseErrorCode
    from bisheng.common.errcode.http_error import ServerError
    from bisheng.common.errcode.linsight import LinsightStartTaskError

    cause = RedisConnectionError(SECRET)
    error = LinsightStartTaskError(exception=cause) if wrapped else cause
    fake = ModuleType("bisheng.workstation.domain.services.task_submit_service")
    fake.submit_task_turn = AsyncMock(side_effect=error)
    monkeypatch.setitem(sys.modules, fake.__name__, fake)
    ns = _namespace()
    ns.update(
        workbench_tenant_id=lambda user: 1,
        SensitiveWordPolicyService=SimpleNamespace(evaluate_workbench_user_text=lambda *a: None),
        BaseErrorCode=BaseErrorCode,
        ServerError=ServerError,
        StreamingResponse=StreamingResponse,
    )
    chat = _chat({"_task_mode_stream_completion"}, ns)
    response = await chat._task_mode_stream_completion(None, SimpleNamespace(text="question"), SimpleNamespace())
    chunks = [chunk async for chunk in response.body_iterator]
    text = "".join(chunk.decode() if isinstance(chunk, bytes) else chunk for chunk in chunks)
    assert SECRET not in text
    payload = json.loads(text.split("data: ", 1)[1])
    assert payload["data"]["failure_info"]["category"] == "database"
