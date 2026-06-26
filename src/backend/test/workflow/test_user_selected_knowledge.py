import asyncio
import importlib
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from bisheng.api.v1.schema.workflow import WorkflowEventType
from bisheng.knowledge.domain.services.knowledge_space_chat_service import KnowledgeSpaceChatService
from bisheng.workflow.common.knowledge import RagUtils
from bisheng.workflow.common.node import NodeType
from bisheng.workflow.common.runtime_knowledge import (
    RUNTIME_KNOWLEDGE_SELECTION_FIELD,
    RUNTIME_STATE_NODE_ID,
    RUNTIME_USER_SELECTED_KNOWLEDGE_KEY,
    RuntimeKnowledgeSelection,
    parse_runtime_knowledge_selection,
)
from bisheng.workflow.common.workflow import WorkflowStatus
from bisheng.workflow.graph.graph_engine import GraphEngine
from bisheng.workflow.graph.graph_state import GraphState
from bisheng.workflow.graph.workflow import Workflow
from bisheng.workflow.nodes.node_manage import NODE_CLASS_MAP
from bisheng.workflow.nodes.user_selected_knowledge_retriever.user_selected_knowledge_retriever import (
    UserSelectedKnowledgeRetriever,
)


def _workflow_node(data: dict) -> dict:
    return {"id": data["id"], "data": data}


def _runtime_selection_payload() -> dict:
    return {
        "mode": "source",
        "whole_source": {
            "source_type": "knowledge",
            "source_id": 11,
            "source_name": "kb",
        },
        "items": [],
        "effective_file_count": None,
    }


def _minimal_runtime_workflow_data() -> dict:
    return {
        "nodes": [
            _workflow_node(
                {
                    "id": "start",
                    "type": NodeType.START.value,
                    "name": "开始",
                    "v": 1,
                    "group_params": [
                        {
                            "name": "基础",
                            "params": [
                                {"key": "guide_word", "value": ""},
                                {"key": "guide_question", "value": []},
                                {"key": "preset_question", "value": []},
                                {"key": "chat_history", "value": 10},
                                {"key": "custom_variables", "value": []},
                            ],
                        }
                    ],
                }
            ),
            _workflow_node(
                {
                    "id": "runtime",
                    "type": NodeType.USER_SELECTED_KNOWLEDGE_RETRIEVER.value,
                    "name": "自选知识检索",
                    "v": 1,
                    "group_params": [],
                }
            ),
            _workflow_node(
                {
                    "id": "end",
                    "type": NodeType.END.value,
                    "name": "结束",
                    "v": 1,
                    "group_params": [],
                }
            ),
        ],
        "edges": [
            {
                "id": "e1",
                "source": "start",
                "sourceHandle": "source",
                "target": "runtime",
                "targetHandle": "target",
            },
            {
                "id": "e2",
                "source": "runtime",
                "sourceHandle": "source",
                "target": "end",
                "targetHandle": "target",
            },
        ],
    }


def _import_redis_callback():
    spec = importlib.util.spec_from_file_location(
        "_test_redis_callback",
        Path(__file__).parents[2] / "bisheng" / "worker" / "workflow" / "redis_callback.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.RedisCallback


def test_runtime_selection_normalizes_legacy_folder_scope():
    selection = parse_runtime_knowledge_selection(
        {
            "type": "knowledge",
            "source_id": 1,
            "source_name": "kb",
            "files": [],
            "folders": [{"id": 2, "name": "folder"}],
            "effective_file_count": 1,
        }
    )

    assert selection.mode == "items"
    assert selection.items[0].source_type == "knowledge"
    assert selection.items[0].source_id == 1
    assert selection.items[0].ref_type == "folder"


def test_graph_engine_extracts_runtime_selection_from_input_params():
    engine = object.__new__(GraphEngine)
    engine.graph_state = GraphState()

    cleaned = engine._extract_runtime_input(
        {
            "user_input": "question",
            RUNTIME_KNOWLEDGE_SELECTION_FIELD: {
                "mode": "items",
                "whole_source": None,
                "items": [
                    {
                        "source_type": "knowledge",
                        "source_id": 11,
                        "source_name": "kb",
                        "ref_type": "file",
                        "id": 101,
                        "name": "doc.pdf",
                    }
                ],
                "effective_file_count": 1,
            },
        }
    )

    assert RUNTIME_KNOWLEDGE_SELECTION_FIELD not in cleaned
    assert cleaned["user_input"] == "question"
    stored = engine.graph_state.get_variable(RUNTIME_STATE_NODE_ID, RUNTIME_USER_SELECTED_KNOWLEDGE_KEY)
    assert stored["mode"] == "items"
    assert stored["items"][0]["source_type"] == "knowledge"
    assert stored["items"][0]["source_id"] == 11
    assert stored["items"][0]["id"] == 101


def test_graph_engine_requests_runtime_selection_before_user_selected_node():
    callback = MagicMock()
    engine = object.__new__(GraphEngine)
    engine.graph_state = GraphState()
    engine.graph_config = {}
    engine.callback = callback
    engine.status = WorkflowStatus.RUNNING.value
    engine.nodes_map = {
        "runtime_node": SimpleNamespace(
            type=NodeType.USER_SELECTED_KNOWLEDGE_RETRIEVER.value,
            name="自选知识检索",
        )
    }
    engine.graph = SimpleNamespace(get_state=lambda _: SimpleNamespace(next=("runtime_node",)))

    engine.judge_status()

    assert engine.status == WorkflowStatus.INPUT.value
    callback.on_user_input.assert_called_once()
    input_data = callback.on_user_input.call_args.args[0]
    assert input_data.node_id == "runtime_node"
    assert input_data.input_schema["tab"] == "runtime_knowledge"
    assert input_data.input_schema["key"] == RUNTIME_KNOWLEDGE_SELECTION_FIELD


def test_graph_engine_continues_when_runtime_selection_already_exists():
    callback = MagicMock()
    engine = object.__new__(GraphEngine)
    engine.graph_state = GraphState()
    engine.graph_state.set_variable(
        RUNTIME_STATE_NODE_ID,
        RUNTIME_USER_SELECTED_KNOWLEDGE_KEY,
        {
            "mode": "source",
            "whole_source": {"source_type": "knowledge", "source_id": 11, "source_name": "kb"},
            "items": [],
            "effective_file_count": None,
        },
    )
    engine.graph_config = {}
    engine.callback = callback
    engine.status = WorkflowStatus.INPUT.value
    engine.nodes_map = {
        "runtime_node": SimpleNamespace(
            type=NodeType.USER_SELECTED_KNOWLEDGE_RAG.value,
            name="自选知识问答",
        )
    }
    engine.graph = SimpleNamespace(get_state=lambda _: SimpleNamespace(next=("runtime_node",)))

    engine.judge_status()

    assert engine.status == WorkflowStatus.RUNNING.value
    callback.on_user_input.assert_not_called()


def test_runtime_knowledge_input_updates_waiting_message_without_question():
    redis_callback = _import_redis_callback()
    selection = _runtime_selection_payload()
    old_message = {
        "node_id": "runtime",
        "name": "自选知识检索",
        "input_schema": {
            "tab": "runtime_knowledge",
            "key": RUNTIME_KNOWLEDGE_SELECTION_FIELD,
        },
    }
    message_db = SimpleNamespace(
        category=WorkflowEventType.UserInput.value,
        message=json.dumps(old_message, ensure_ascii=False),
    )

    chat_response, updated_message = redis_callback._update_old_message(
        {"runtime": {RUNTIME_KNOWLEDGE_SELECTION_FIELD: selection}},
        message_db,
        message_content="",
        verify_input=True,
    )

    assert chat_response is None
    assert updated_message is message_db
    assert json.loads(message_db.message)["hisValue"] == selection


def test_workflow_run_resumes_user_selected_node_after_runtime_selection(monkeypatch):
    executed_nodes = []

    def fake_runtime_run(self, unique_id):
        executed_nodes.append(self.id)
        return {"result": "ok"}

    monkeypatch.setattr(UserSelectedKnowledgeRetriever, "_run", fake_runtime_run)
    monkeypatch.setattr(UserSelectedKnowledgeRetriever, "parse_log", lambda self, unique_id, result: [])

    callback = MagicMock()
    workflow = Workflow(
        workflow_id="workflow-id",
        user_id=None,
        workflow_data=_minimal_runtime_workflow_data(),
        max_steps=10,
        callback=callback,
    )

    assert workflow.run() == (WorkflowStatus.INPUT.value, "")
    callback.on_user_input.assert_called_once()
    assert executed_nodes == []

    assert workflow.run({"runtime": {RUNTIME_KNOWLEDGE_SELECTION_FIELD: _runtime_selection_payload()}}) == (
        WorkflowStatus.SUCCESS.value,
        "",
    )
    assert executed_nodes == ["runtime"]


def test_new_backend_node_types_are_registered():
    assert NODE_CLASS_MAP[NodeType.USER_SELECTED_KNOWLEDGE_RAG.value]
    assert NODE_CLASS_MAP[NodeType.USER_SELECTED_KNOWLEDGE_RETRIEVER.value]


def test_runtime_knowledge_scope_validates_files(monkeypatch):
    obj = object.__new__(RagUtils)
    selection = RuntimeKnowledgeSelection.model_validate(
        {
            "type": "knowledge",
            "source_id": 11,
            "files": [{"id": 101, "name": "doc.pdf"}],
            "folders": [],
            "effective_file_count": 1,
        }
    )
    monkeypatch.setattr(
        "bisheng.workflow.common.knowledge.KnowledgeFileDao.get_file_by_ids",
        lambda file_ids: [
            SimpleNamespace(id=101, knowledge_id=11, file_type=1, status=2),
        ],
    )

    assert obj._resolve_runtime_knowledge_scope(selection) == {11: [101]}


def test_runtime_knowledge_scope_rejects_invalid_files(monkeypatch):
    obj = object.__new__(RagUtils)
    selection = RuntimeKnowledgeSelection.model_validate(
        {
            "type": "knowledge",
            "source_id": 11,
            "files": [{"id": 101, "name": "doc.pdf"}],
            "folders": [],
            "effective_file_count": 1,
        }
    )
    monkeypatch.setattr(
        "bisheng.workflow.common.knowledge.KnowledgeFileDao.get_file_by_ids",
        lambda file_ids: [
            SimpleNamespace(id=101, knowledge_id=12, file_type=1, status=2),
        ],
    )

    with pytest.raises(ValueError, match="不属于当前知识库"):
        obj._resolve_runtime_knowledge_scope(selection)


def test_runtime_selection_rejects_mixed_item_source_types():
    with pytest.raises(ValueError, match="不能同时选择知识库和知识空间"):
        RuntimeKnowledgeSelection.model_validate(
            {
                "mode": "items",
                "whole_source": None,
                "items": [
                    {"source_type": "knowledge", "source_id": 11, "ref_type": "file", "id": 101, "name": "doc.pdf"},
                    {"source_type": "space", "source_id": 12, "ref_type": "file", "id": 1001, "name": "space.md"},
                ],
                "effective_file_count": 2,
            }
        )


def test_runtime_item_scope_groups_knowledge_items(monkeypatch):
    obj = object.__new__(RagUtils)
    selection = RuntimeKnowledgeSelection.model_validate(
        {
            "mode": "items",
            "whole_source": None,
            "items": [
                {"source_type": "knowledge", "source_id": 11, "ref_type": "file", "id": 101, "name": "doc.pdf"},
                {"source_type": "knowledge", "source_id": 11, "ref_type": "folder", "id": 201, "name": "folder"},
                {"source_type": "knowledge", "source_id": 12, "ref_type": "file", "id": 301, "name": "other.pdf"},
            ],
            "effective_file_count": 4,
        }
    )
    monkeypatch.setattr(
        "bisheng.workflow.common.knowledge.KnowledgeFileDao.get_file_by_ids",
        lambda file_ids: [
            SimpleNamespace(id=101, knowledge_id=11, file_type=1, status=2),
            SimpleNamespace(id=201, knowledge_id=11, file_type=0, status=2, file_level_path=""),
            SimpleNamespace(id=301, knowledge_id=12, file_type=1, status=2),
        ],
    )
    monkeypatch.setattr(RagUtils, "_resolve_folder_success_file_ids", lambda self, folder: [102, 103])

    knowledge_ids, space_ids = obj._resolve_runtime_item_scope(selection)

    assert knowledge_ids == {11: [101, 102, 103], 12: [301]}
    assert space_ids is None


def test_runtime_whole_knowledge_scope_is_valid_without_file_filter():
    obj = object.__new__(RagUtils)
    selection = RuntimeKnowledgeSelection.model_validate(
        {
            "type": "knowledge",
            "source_id": 11,
            "files": [],
            "folders": [],
            "effective_file_count": 0,
        }
    )

    assert obj._resolve_runtime_knowledge_scope(selection) is None


def test_runtime_whole_space_scope_is_valid_without_file_filter():
    obj = object.__new__(RagUtils)
    selection = RuntimeKnowledgeSelection.model_validate(
        {
            "type": "space",
            "source_id": 12,
            "files": [],
            "folders": [],
            "effective_file_count": 0,
        }
    )

    assert obj._resolve_runtime_space_scope(selection) is None


def test_apply_runtime_selection_missing_value_raises_clear_error():
    obj = object.__new__(RagUtils)
    obj.graph_state = GraphState()

    with pytest.raises(ValueError, match="请选择知识库或知识空间"):
        obj.apply_runtime_knowledge_selection()


def test_multiple_runtime_nodes_read_same_selection(monkeypatch):
    graph_state = GraphState()
    graph_state.set_variable(
        RUNTIME_STATE_NODE_ID,
        RUNTIME_USER_SELECTED_KNOWLEDGE_KEY,
        {
            "source_type": "knowledge",
            "source_id": 11,
            "source_name": "kb",
            "files": [],
            "folders": [],
            "effective_file_count": 0,
        },
    )

    monkeypatch.setattr(RagUtils, "_resolve_runtime_knowledge_scope", lambda self, selection: None)

    first = object.__new__(RagUtils)
    first.graph_state = graph_state
    first._knowledge_auth = False
    second = object.__new__(RagUtils)
    second.graph_state = graph_state
    second._knowledge_auth = False

    first.apply_runtime_knowledge_selection()
    second.apply_runtime_knowledge_selection()

    assert first._knowledge_type == "knowledge"
    assert second._knowledge_type == "knowledge"
    assert first._knowledge_value == [11]
    assert second._knowledge_value == [11]
    assert first._knowledge_auth is True
    assert second._knowledge_auth is True


def test_runtime_knowledge_retriever_forces_backend_permission_check(monkeypatch):
    obj = object.__new__(RagUtils)
    obj.user_id = 7
    obj.user_info = SimpleNamespace(user_name="tester")
    obj._knowledge_value = [11]
    obj._knowledge_vector_list = []
    obj._knowledge_auth = False
    obj._runtime_selection_required = True
    obj._keyword_weight = 0.5
    obj._vector_weight = 0.5
    captured = {}

    def _fake_get_multi(**kwargs):
        captured.update(kwargs)
        return {}

    monkeypatch.setattr(
        "bisheng.workflow.common.knowledge.KnowledgeRag.get_multi_knowledge_vectorstore_sync",
        _fake_get_multi,
    )

    with pytest.raises(ValueError, match="所选知识库不存在或无权限访问"):
        obj.init_knowledge_retriever()

    assert captured["check_auth"] is True
    assert captured["knowledge_ids"] == [11]


def test_runtime_file_filter_combines_with_existing_filters():
    obj = object.__new__(RagUtils)
    obj._runtime_selected_file_ids_by_knowledge = {11: [101, 102]}

    milvus_expr, es_filter = obj._apply_runtime_file_filter(
        11,
        "document_id not in [9]",
        [{"range": {"metadata.upload_time": {"gte": 1}}}],
    )

    assert milvus_expr == "(document_id not in [9]) and (document_id in [101, 102])"
    assert es_filter == [
        {"range": {"metadata.upload_time": {"gte": 1}}},
        {"terms": {"metadata.document_id": [101, 102]}},
    ]


def test_retrieve_space_question_passes_runtime_file_ids(monkeypatch):
    obj = object.__new__(RagUtils)
    obj._knowledge_value = [12]
    obj._runtime_selected_file_ids_by_space = {12: [1001, 1002]}
    obj._retriever_kwargs = {"k": 5}
    obj._max_chunk_size = 1024
    obj.user_info = SimpleNamespace(user_id=7, user_name="tester")
    captured = {}

    def _fake_retrieve(**kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(
        "bisheng.workflow.common.knowledge.retrieve_knowledge_space_documents_sync",
        _fake_retrieve,
    )

    obj.retrieve_space_question("question")

    assert captured["kb_filters"] == {12: {"file_ids": [1001, 1002]}}


@pytest.mark.asyncio
async def test_space_chunk_retrieval_passes_file_ids_to_kb_retriever():
    svc = object.__new__(KnowledgeSpaceChatService)
    captured = []

    async def _fake_retrieve(kb_id, *, query, tag_names, file_ids, max_content):
        captured.append((kb_id, query, tag_names, file_ids, max_content))
        return []

    svc._aretrieve_chunks_for_kb = _fake_retrieve

    await svc.aretrieve_chunks(
        query="question",
        knowledge_base_ids=[12],
        kb_filters={12: {"file_ids": [1001], "tags": ["tag"]}},
        max_content=1024,
    )

    assert captured == [(12, "question", ["tag"], [1001], 1024)]


def test_user_selected_retriever_keeps_runtime_errors_as_node_errors():
    obj = object.__new__(UserSelectedKnowledgeRetriever)
    obj._output_keys = ["retrieved_result"]
    obj.init_user_question = MagicMock(return_value=["question"])
    obj.init_user_info = MagicMock()
    obj.apply_runtime_knowledge_selection = MagicMock()
    obj.init_multi_retriever = MagicMock(side_effect=RuntimeError("missing runtime selection"))

    with pytest.raises(RuntimeError, match="missing runtime selection"):
        obj._run("unique")


def test_runtime_space_scope_uses_space_service(monkeypatch):
    obj = object.__new__(RagUtils)
    obj.user_info = SimpleNamespace(user_id=7, user_name="tester", user_role=[], tenant_id=1)
    selection = RuntimeKnowledgeSelection.model_validate(
        {
            "type": "space",
            "source_id": 12,
            "files": [{"id": 1001, "name": "doc.pdf"}],
            "folders": [{"id": 2001, "name": "folder"}],
            "effective_file_count": 2,
        }
    )
    captured = {}

    class FakeSpaceService:
        def __init__(self, request, login_user):
            captured["login_user"] = login_user

        async def resolve_qa_scope_file_ids(self, *, folder_refs, file_refs, max_files):
            captured["folder_refs"] = folder_refs
            captured["file_refs"] = file_refs
            captured["max_files"] = max_files
            return {12: [1001, 1002]}

    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceService",
        FakeSpaceService,
    )

    import bisheng

    worker_mod = types.ModuleType("bisheng.worker")
    worker_mod.__path__ = []
    asyncio_utils_mod = types.ModuleType("bisheng.worker._asyncio_utils")
    asyncio_utils_mod.run_async_task = lambda coro_factory: asyncio.run(coro_factory())
    worker_mod._asyncio_utils = asyncio_utils_mod
    monkeypatch.setattr(bisheng, "worker", worker_mod, raising=False)
    monkeypatch.setitem(sys.modules, "bisheng.worker", worker_mod)
    monkeypatch.setitem(sys.modules, "bisheng.worker._asyncio_utils", asyncio_utils_mod)

    assert obj._resolve_runtime_space_scope(selection) == {12: [1001, 1002]}
    assert captured["file_refs"] == [{"knowledge_space_id": 12, "file_id": 1001}]
    assert captured["folder_refs"] == [{"knowledge_space_id": 12, "folder_id": 2001}]
    assert captured["max_files"] == 20
