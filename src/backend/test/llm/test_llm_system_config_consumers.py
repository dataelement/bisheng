"""F022 consumer tenant plumbing plus F118 real default admission regressions.

覆盖 AC: AC-71, AC-79, AC-83, AC-87, AC-89, AC-92
Heavy workflow/linsight plumbing is checked structurally rather than matching
formatting. Actual default helpers use native/async SQL and no provider IO.
"""

import ast
import inspect
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import delete
from sqlmodel import Session

from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.llm.application import model_default_read
from bisheng.llm.domain.models.llm_server import LLMModel
from bisheng.llm.domain.services.llm import LLMService
from bisheng.resource_reference.domain.models.resource_reference_tombstone import ResourceReferenceTombstone
from test.knowledge_unification import test_llm_default_read as reading
from test.knowledge_unification import test_model_default_native_target as native

_BACKEND_ROOT = Path(__file__).resolve().parents[2] / "bisheng"
reads = reading.reads
model_owner_tenant = reading.model_owner_tenant


def tree(path):
    return ast.parse((_BACKEND_ROOT / path).read_text())


def contains(path, expression):
    expected = ast.unparse(ast.parse(expression, mode="eval").body)
    return any(ast.unparse(node) == expected for node in ast.walk(tree(path)) if isinstance(node, ast.expr))


def forwards(path, expression, callee=None):
    expected = ast.unparse(ast.parse(expression, mode="eval").body)
    return any(
        kw.arg == "tenant_id" and ast.unparse(kw.value) == expected
        for node in ast.walk(tree(path))
        if isinstance(node, ast.Call)
        and (callee is None or getattr(node.func, "attr", getattr(node.func, "id", None)) == callee)
        for kw in node.keywords
    )


def function(path, name, class_name=None):
    root = tree(path)
    if class_name:
        root = next(node for node in root.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    return next(
        node
        for node in ast.walk(root)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    )


def has_parameter(node, name):
    return name in {arg.arg for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)}


def test_workflow_init_accepts_tenant_id_kwarg():
    path = "workflow/graph/workflow.py"
    assert has_parameter(function(path, "__init__", "Workflow"), "tenant_id")
    assert contains(path, "self.tenant_id") and forwards(path, "tenant_id")


def test_graph_engine_init_accepts_tenant_id_kwarg():
    path = "workflow/graph/graph_engine.py"
    assert has_parameter(function(path, "__init__", "GraphEngine"), "tenant_id")
    assert contains(path, "self.tenant_id") and forwards(path, "self.tenant_id")


def test_base_node_picks_up_tenant_id_from_kwargs():
    assert contains("workflow/nodes/base.py", "kwargs.get('tenant_id')")
    assert contains("workflow/nodes/base.py", "self.tenant_id")


def test_agent_node_threads_self_tenant_id():
    for method in ("sync_get_assistant_llm", "get_knowledge_default_embedding"):
        assert forwards("workflow/nodes/agent/agent.py", "self.tenant_id", method)
    calls = [node for node in ast.walk(tree("workflow/nodes/agent/agent.py")) if isinstance(node, ast.Call)]
    assert {"sync_get_assistant_llm", "get_knowledge_default_embedding"} <= {
        getattr(node.func, "attr", None) for node in calls
    }


def test_input_node_threads_self_tenant_id():
    assert forwards("workflow/nodes/input/input.py", "self.tenant_id", "get_knowledge_default_embedding")


def test_workflow_common_knowledge_threads_self_tenant_id():
    assert forwards("workflow/common/knowledge.py", "self.tenant_id", "get_knowledge_default_embedding")


def test_tasks_resolves_flow_tenant_once_and_threads():
    path = "worker/workflow/tasks.py"
    assert contains(path, "getattr(workflow_info,'tenant_id',None)")
    assert forwards(path, "flow_tenant_id")
    calls = [node for node in ast.walk(tree(path)) if isinstance(node, ast.Call)]
    assert any(
        getattr(node.func, "id", None) == "Workflow"
        and any(kw.arg == "tenant_id" and ast.unparse(kw.value) == "flow_tenant_id" for kw in node.keywords)
        for node in calls
    )


def test_redis_callback_pops_tenant_id_kwarg_in_init():
    assert any(
        isinstance(node, ast.Call)
        and getattr(node.func, "attr", None) == "pop"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "tenant_id"
        for node in ast.walk(tree("worker/workflow/redis_callback.py"))
    )


def test_redis_callback_session_title_uses_self_tenant():
    assert forwards("worker/workflow/redis_callback.py", "self.tenant_id", "get_workbench_llm_sync")


def test_linsight_task_exec_threads_session_tenant():
    # The live helper now delegates the actual saved session to the shared
    # resolver, which obtains both its explicit model and tenant defaults.
    node = function("linsight/domain/task_exec.py", "_get_llm")
    assert has_parameter(node, "session_model")
    assert contains("linsight/domain/task_exec.py", "_resolve_model(session_model,getattr(session_model,'model',None))")
    assert forwards("linsight/domain/services/agent_factory.py", "session_model.tenant_id", "get_workbench_llm")


def test_evaluation_uses_evaluation_tenant():
    assert forwards("evaluation/domain/services/evaluation_service.py", "evaluation.tenant_id")


def test_file_encoding_uses_knowledge_file_tenant():
    path = "knowledge/rag/pipeline/transformer/file_encoding.py"
    assert contains(path, "getattr(self.knowledge_file,'tenant_id',None)") and forwards(path, "tenant_id")


def test_abstract_transformer_uses_knowledge_file_tenant():
    path = "knowledge/rag/pipeline/transformer/abstract.py"
    assert contains(path, "getattr(self.knowledge_file,'tenant_id',None)") and forwards(path, "tenant_id")


def test_recommend_question_accepts_tenant_id():
    path = "api/services/knowledge_imp.py"
    node = function(path, "recommend_question")
    assert all(has_parameter(node, key) for key in ("invoke_user_id", "question", "answer", "number", "tenant_id"))
    assert forwards(path, "tenant_id")
    assert not any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in {"decide_knowledge_llm", "async_decide_knowledge_llm"}
        for node in ast.walk(tree(path))
    )


def test_knowledge_utils_abstract_llm_accepts_tenant_id():
    assert has_parameter(
        function("knowledge/domain/services/knowledge_utils.py", "get_knowledge_abstract_llm"), "tenant_id"
    )


def test_llm_service_helpers_accept_tenant_id():
    for name in (
        "get_knowledge_source_llm",
        "get_knowledge_source_llm_async",
        "get_knowledge_similar_llm",
        "get_knowledge_default_embedding",
        "get_evaluation_llm_object",
    ):
        assert inspect.signature(getattr(LLMService, name)).parameters["tenant_id"].default is None


@pytest.fixture
async def admitted_defaults(reads, monkeypatch):
    monkeypatch.setattr(model_default_read, "_runtime", reads.facade)
    return reads


@pytest.mark.parametrize(
    "method,provider",
    [
        ("get_knowledge_source_llm", "get_bisheng_llm_sync"),
        ("get_knowledge_similar_llm", "get_bisheng_llm_sync"),
        ("get_knowledge_default_embedding", "get_bisheng_knowledge_embedding_sync"),
    ],
)
async def test_native_live_helpers_consume_original_admitted_id_and_reject_tenant_override(
    admitted_defaults, monkeypatch, method, provider
):
    with Session(admitted_defaults.engine) as session, session.begin():
        native.seed_default(
            session,
            key="knowledge_llm",
            payload={"source_model_id": 11, "qa_similar_model_id": 11, "embedding_model_id": 11},
        )
    sentinel = object()
    model = Mock(return_value=sentinel)
    monkeypatch.setattr(LLMService, provider, model)
    assert getattr(LLMService, method)(7, tenant_id=101) is sentinel
    assert (
        model.call_args.kwargs["model_id"] == 11
        and model.call_args.kwargs.get("user_id", model.call_args.kwargs.get("invoke_user_id")) == 7
    )
    assert get_current_tenant_id() == 101
    model.reset_mock()
    with pytest.raises(ResourceReferenceInvalidError):
        getattr(LLMService, method)(7, tenant_id=202)
    model.assert_not_called()


async def test_async_live_helper_uses_same_whole_source_before_provider(admitted_defaults, monkeypatch):
    with Session(admitted_defaults.engine) as session, session.begin():
        native.seed_default(session, key="knowledge_llm", payload={"source_model_id": 11})
    model = AsyncMock(return_value="actual-client-boundary")
    monkeypatch.setattr(LLMService, "get_bisheng_llm", model)
    assert await LLMService.get_knowledge_source_llm_async(7, tenant_id=101) == "actual-client-boundary"
    assert model.await_args.kwargs["model_id"] == 11 and model.await_args.kwargs["user_id"] == 7


async def test_invalid_other_slot_blocks_actual_default_consumer_before_provider(admitted_defaults, monkeypatch):
    with Session(admitted_defaults.engine) as session, session.begin():
        native.seed_default(session, key="knowledge_llm", payload={"source_model_id": 22, "extract_title_model_id": 11})
        session.execute(delete(LLMModel).where(LLMModel.tenant_id == 101, LLMModel.id == 11))
        session.add(
            ResourceReferenceTombstone(
                tenant_id=101,
                target_tenant_id=101,
                target_type="model",
                target_id="11",
                operation_id="deleted-title",
                operation_type="force_delete_model",
                actor_type="user",
                actor_id="7",
                stage="deleted",
            )
        )
    model = Mock(side_effect=AssertionError("invalid optional default reached provider"))
    monkeypatch.setattr(LLMService, "get_bisheng_llm_sync", model)
    with pytest.raises(ResourceReferenceInvalidError):
        LLMService.get_knowledge_source_llm(7, tenant_id=101)
    model.assert_not_called()
