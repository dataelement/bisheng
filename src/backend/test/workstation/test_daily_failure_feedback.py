"""Execute real daily boundaries with isolated infrastructure dependencies.

The AST loader avoids application startup and the root conftest's worker imports;
only external collaborators are replaced. The function bodies are production code.
"""

import ast
import asyncio
import json
import os
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
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
    namespace = {"json": json, "logger": logger}
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
        cls, "policy", SimpleNamespace(organization_knowledge_ids=[1, 2], knowledge_space_ids=[]), 1000, user
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


@pytest.fixture
def stream_env():
    from bisheng.common.errcode.base import BaseErrorCode
    from bisheng.common.errcode.http_error import ServerError
    from bisheng.common.errcode.workstation import LLMRateLimitError

    namespace = _namespace()
    inserted = []
    exc = RedisConnectionError(SECRET)

    class _LLM:
        async def astream(self, _messages):
            yield SimpleNamespace(content="partial answer", additional_kwargs={})
            raise exc

    def insert(row):
        row.id = 900
        inserted.append(row)
        return row

    namespace.update(
        asyncio=asyncio,
        time=time,
        datetime=datetime,
        uuid4=uuid4,
        _os=os,
        BaseErrorCode=BaseErrorCode,
        ServerError=ServerError,
        HTTPException=HTTPException,
        LLMRateLimitError=LLMRateLimitError,
        StreamingResponse=StreamingResponse,
        HumanMessage=HumanMessage,
        SystemMessage=SystemMessage,
        ChatMessage=SimpleNamespace,
        ChatMessageDao=SimpleNamespace(
            ainsert_one=AsyncMock(side_effect=insert), insert_one=MagicMock(side_effect=insert)
        ),
        _agent_initialize_chat=AsyncMock(
            return_value=(
                SimpleNamespace(systemPrompt=""),
                SimpleNamespace(chat_id="chat-1", user_id=7, name="existing"),
                SimpleNamespace(id=101),
                _LLM(),
                SimpleNamespace(displayName="visible model"),
                False,
                "execution",
                "attempt",
            )
        ),
        _resolve_user_kb_selection=AsyncMock(return_value=[]),
        _prepare_tools=AsyncMock(return_value=([], [])),
        _process_agent_files=AsyncMock(return_value=("", [], [])),
        _get_history_max_tokens=AsyncMock(return_value=4096),
        _get_agent_max_iterations=AsyncMock(return_value=50),
        _build_user_content=MagicMock(return_value="question"),
        _serialize_message=lambda message: message,
        _persist_question_file_attachments=AsyncMock(),
        WorkStationService=SimpleNamespace(get_chat_history=AsyncMock(return_value=[])),
        DepartmentFlowService=SimpleNamespace(resolve_limit_and_dept=AsyncMock(return_value=(0, None))),
        CitationRegistryCollector=lambda: SimpleNamespace(list_items=lambda: []),
        select_registry_items_for_persistence=lambda items, text: [],
        strip_unregistered_citation_markers=lambda text, items: text,
        save_message_citations=AsyncMock(),
        save_message_citations_sync=MagicMock(),
        log_telemetry_events=AsyncMock(),
        _sse_resp=lambda category, status, data, *args, **kwargs: json.dumps(
            {"category": category, "type": status, "data": data}
        ),
        trace_id_var=SimpleNamespace(get=lambda: None),
        user_message=lambda *args: json.dumps({"category": "question"}),
        ApplicationTypeEnum=SimpleNamespace(DAILY_CHAT=SimpleNamespace(value="daily_chat")),
        build_daily_model_call_context=MagicMock(),
        ModelRateLimitService=lambda: SimpleNamespace(
            list_model_states=AsyncMock(return_value={17: SimpleNamespace(status_version=0)}),
            observe_call_failure=AsyncMock(return_value=None),
            observe_call_success=AsyncMock(),
        ),
        label_error=lambda exc: SimpleNamespace(value="unknown"),
        unwrap=lambda exc: exc,
        ErrorType=SimpleNamespace(
            UNKNOWN=SimpleNamespace(value="unknown"), RATE_LIMIT=SimpleNamespace(value="rate_limit")
        ),
    )
    chat = _chat({"_agent_stream_chat_completion"}, namespace)
    return SimpleNamespace(chat=chat, inserted=inserted, namespace=namespace)


async def test_terminal_failure_sse_and_history_share_source(stream_env):
    data = SimpleNamespace(
        model="17", text="question", tools=[], files=[], use_knowledge_base=None, conversationId="chat-1"
    )
    response = await stream_env.chat._agent_stream_chat_completion(
        MagicMock(), data, SimpleNamespace(tenant_id=1, user_id=7)
    )
    chunks = [chunk async for chunk in response.body_iterator]
    error = next(
        json.loads(chunk.split("data: ", 1)[1])["data"] for chunk in chunks if chunk.startswith("event: error")
    )
    [row] = stream_env.inserted
    extra = json.loads(row.extra)
    assert error["failure_info"]["category"] == "database"
    assert error["failure_info"] == extra["failure_info"]
    assert json.loads(row.message)["msg"] == "partial answer"
    assert SECRET not in "".join(chunks) + row.extra


async def test_secondary_recovery_store_failure_cannot_hide_original_service_error(stream_env):
    service = stream_env.namespace["ModelRateLimitService"]()
    service.observe_call_failure.side_effect = RuntimeError("secondary store failed")
    stream_env.namespace["ModelRateLimitService"] = lambda: service
    data = SimpleNamespace(
        model="17", text="question", tools=[], files=[], use_knowledge_base=None, conversationId="chat-1"
    )
    response = await stream_env.chat._agent_stream_chat_completion(
        MagicMock(), data, SimpleNamespace(tenant_id=1, user_id=7)
    )
    chunks = [chunk async for chunk in response.body_iterator]
    error = next(
        json.loads(chunk.split("data: ", 1)[1])["data"] for chunk in chunks if chunk.startswith("event: error")
    )
    assert error["failure_info"]["category"] == "database"
    assert "secondary store failed" not in "".join(chunks)


async def test_answer_persistence_failure_reports_database_instead_of_transport(stream_env):
    stream_env.namespace["ChatMessageDao"].ainsert_one.side_effect = RedisConnectionError(SECRET)
    data = SimpleNamespace(
        model="17", text="question", tools=[], files=[], use_knowledge_base=None, conversationId="chat-1"
    )
    response = await stream_env.chat._agent_stream_chat_completion(
        MagicMock(), data, SimpleNamespace(tenant_id=1, user_id=7)
    )
    chunks = [chunk async for chunk in response.body_iterator]
    errors = [json.loads(chunk.split("data: ", 1)[1])["data"] for chunk in chunks if chunk.startswith("event: error")]
    assert errors[-1]["failure_info"]["category"] == "database"
    assert "partial answer" in "".join(chunks)
    assert SECRET not in "".join(chunks)


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
