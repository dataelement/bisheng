"""Offline regressions executing production AST without importing service infrastructure."""

import ast
import asyncio
from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

BACKEND = Path(__file__).resolve().parents[2]
CLIENT = BACKEND / "bisheng/common/chat/clients/workflow_client.py"
CALLBACK = BACKEND / "bisheng/worker/workflow/redis_callback.py"
KNOWLEDGE = BACKEND / "bisheng/workflow/common/knowledge.py"


class InvalidInput(Exception):
    def __init__(self, *, msg):
        super().__init__(msg)


def load_methods(path, class_name, names, namespace):
    tree = ast.parse(path.read_text())
    owner = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    owner.body = [node for node in owner.body if getattr(node, "name", None) in names]
    owner.bases = []
    module = ast.Module(
        body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), owner],
        type_ignores=[],
    )
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)
    return namespace[class_name]


@pytest.fixture
def callback_class():
    return load_methods(
        CALLBACK,
        "RedisCallback",
        {
            "_verify_node_input",
            "_verify_input_schema",
            "_verify_pending_input",
            "set_user_input",
            "async_set_user_input",
        },
        {"WorkFlowInvalidUserInputError": InvalidInput, "nullcontext": nullcontext},
    )


def test_workflow_boundary_imports_have_exact_sources():
    imports = {
        alias.asname or alias.name: node.module
        for node in ast.parse(CLIENT.read_text()).body
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert {
        name: imports.get(name)
        for name in ("NotFoundError", "require_business_action", "WorkFlowInvalidUserInputError")
    } == {
        "NotFoundError": "bisheng.common.errcode.http_error",
        "require_business_action": "bisheng.permission.application.business_authorization",
        "WorkFlowInvalidUserInputError": "bisheng.common.errcode.flow",
    }


DIALOG = {"node_id": "input_1", "input_schema": {"tab": "dialog_input", "key": "user_input"}}


@pytest.mark.parametrize("fields", [{"user_input": "hi"}, {"user_input": "hi", "dialog_files_content": []}])
def test_dialog_accepts_only_declared_text_and_optional_files(callback_class, fields):
    callback_class._verify_input_schema(DIALOG, {"input_1": fields})


@pytest.mark.parametrize(
    "data",
    [
        {"input_1": {"user_input": "hi", "code": "inert"}},
        {"input_1": {"user_input": "hi"}, "tool_1": {}},
        {"input_1": {"dialog_files_content": []}},
        {"input_1": "hi"},
    ],
)
def test_dialog_rejects_extra_fields_nodes_and_missing_text(callback_class, data):
    with pytest.raises(InvalidInput):
        callback_class._verify_input_schema(DIALOG, data)


@pytest.mark.parametrize("async_mode", [False, True])
def test_invalid_dialog_is_rejected_before_message_or_redis_mutation(callback_class, async_mode):
    callback = callback_class()
    pending = {"message": DIALOG, "message_id": 7}
    callback.workflow_pending_key = "pending"
    callback.redis_client = SimpleNamespace(
        get=Mock(return_value=pending), aget=AsyncMock(return_value=pending), set=Mock(), aset=AsyncMock()
    )
    callback.update_old_message = Mock()
    callback.async_update_old_message = AsyncMock()
    callback.chat_id, callback.workflow_id, callback.user_id = "", "workflow", 2
    callback.workflow_input_key, callback.workflow_expire_time = "input", 60
    data = {"input_1": {"user_input": "hi", "code": "inert"}}
    with pytest.raises(InvalidInput):
        if async_mode:
            asyncio.run(callback.async_set_user_input(data, message_id=7, verify_input=True))
        else:
            callback.set_user_input(data, message_id=7, verify_input=True)
    callback.redis_client.set.assert_not_called()
    callback.redis_client.aset.assert_not_awaited()
    callback.update_old_message.assert_not_called()
    callback.async_update_old_message.assert_not_awaited()


def test_rag_loop_binds_each_space_and_preserves_primary_only_filter():
    tree = ast.parse(KNOWLEDGE.read_text())
    method = next(
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "init_knowledge_retriever"
    )
    # Start after authorization/vector construction; do not mock the permission runtime.
    start = next(
        i
        for i, node in enumerate(method.body)
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "all_milvus" for t in node.targets)
    )
    method.body = method.body[start:]
    calls = []
    wrappers = []

    def primary_filter(excluded, **kwargs):
        calls.append((excluded, kwargs))
        return kwargs["base_milvus_expr"], kwargs["base_es_filter"]

    def wrapper(vector, postfilter):
        wrappers.append(postfilter)
        return vector

    namespace = {
        "deepcopy": deepcopy,
        "build_primary_only_filter": primary_filter,
        "_ScopedKnowledgeVector": wrapper,
        "MultiRetriever": lambda **kwargs: kwargs,
        "logger": SimpleNamespace(debug=lambda *args: None),
    }
    exec(
        compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])), str(KNOWLEDGE), "exec"),
        namespace,
    )
    scopes = {i: SimpleNamespace(is_empty=False, milvus_expr=f"space_{i}", es_filter=[{"space": i}]) for i in (12, 13)}
    postfilter = AsyncMock(return_value=[])
    node = SimpleNamespace(
        _knowledge_vector_list={i: {"knowledge": i, "milvus": object(), "es": object()} for i in (11, 12, 13)},
        _legacy_space_filters=scopes,
        _metadata_filter=SimpleNamespace(get_knowledge_filter=lambda **kwargs: ("base", {"filter": [{"base": True}]})),
        _fetch_non_primary_file_ids=Mock(return_value=[99]),
        _retriever_kwargs={"k": 4},
        _apostfilter_legacy_space_scores=postfilter,
    )
    namespace[method.name](node)
    node._fetch_non_primary_file_ids.assert_called_once_with([11])
    assert [call[0] for call in calls] == [[99], [], []]
    assert len(node._multi_milvus_retriever["vectors"]) == 3
    assert len(node._multi_es_retriever["vectors"]) == 3
    assert "space_12" in calls[1][1]["base_milvus_expr"]
    assert calls[2][1]["base_es_filter"][-1] == {"space": 13}
    for post in wrappers:
        asyncio.run(post([]))
    assert [call.args[0] for call in postfilter.await_args_list] == [12, 12, 13, 13]
