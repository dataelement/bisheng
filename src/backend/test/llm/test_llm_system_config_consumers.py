"""F022 T04 Consumer-side tenant_id threading tests.

Verifies the F022 INV-T18 wiring carries Flow.tenant_id from the celery
task entry through every layer that needs it.

The dev venv lacks several optional deps (elasticsearch, langchain.memory,
…) that the Workflow stack pulls in transitively. To stay independent of
those, the assertions use ``inspect.getsource`` against the relevant
files — verifying the contract rather than executing the layers.
"""
import re
from pathlib import Path

# All assertions read the file directly so we don't trigger heavy imports.
_BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent / 'bisheng'


def _read(rel_path: str) -> str:
    return (_BACKEND_ROOT / rel_path).read_text(encoding='utf-8')


# --- Workflow → GraphEngine → BaseNode threading ---------------------------


def test_workflow_init_accepts_tenant_id_kwarg():
    src = _read('workflow/graph/workflow.py')
    assert 'tenant_id: int = None' in src
    assert 'self.tenant_id = tenant_id' in src
    assert 'tenant_id=tenant_id' in src  # forwarded to GraphEngine


def test_graph_engine_init_accepts_tenant_id_kwarg():
    src = _read('workflow/graph/graph_engine.py')
    assert 'tenant_id: int = None' in src
    assert 'self.tenant_id = tenant_id' in src
    # Forwarded to NodeFactory at node construction time.
    assert 'tenant_id=self.tenant_id' in src


def test_base_node_picks_up_tenant_id_from_kwargs():
    src = _read('workflow/nodes/base.py')
    assert "self.tenant_id" in src
    assert "kwargs.get('tenant_id')" in src


# --- 4 workflow node sites use self.tenant_id ------------------------------


def test_agent_node_threads_self_tenant_id():
    src = _read('workflow/nodes/agent/agent.py')
    # _init_agent: assistant_llm
    assert 'sync_get_assistant_llm(tenant_id=self.tenant_id)' in src
    # init_file_milvus: knowledge_default_embedding
    assert 'get_knowledge_default_embedding(self.user_id, tenant_id=self.tenant_id)' in src


def test_input_node_threads_self_tenant_id():
    src = _read('workflow/nodes/input/input.py')
    assert 'get_knowledge_default_embedding(self.user_id, tenant_id=self.tenant_id)' in src


def test_workflow_common_knowledge_threads_self_tenant_id():
    src = _read('workflow/common/knowledge.py')
    assert 'get_knowledge_default_embedding(self.user_id, tenant_id=self.tenant_id)' in src


# --- Celery task entry threads Flow.tenant_id ------------------------------


def test_tasks_resolves_flow_tenant_once_and_threads():
    src = _read('worker/workflow/tasks.py')
    assert "flow_tenant_id = getattr(workflow_info, 'tenant_id', None)" in src
    # Both consumers receive it.
    assert 'tenant_id=flow_tenant_id' in src
    # Workflow constructor receives it positionally or as kwarg.
    assert re.search(r'Workflow\([^)]*tenant_id=flow_tenant_id', src, re.DOTALL)


def test_redis_callback_pops_tenant_id_kwarg_in_init():
    src = _read('worker/workflow/redis_callback.py')
    assert "kwargs.pop('tenant_id'" in src or 'kwargs.pop("tenant_id"' in src


def test_redis_callback_session_title_uses_self_tenant():
    src = _read('worker/workflow/redis_callback.py')
    assert 'get_workbench_llm_sync(tenant_id=self.tenant_id)' in src


# --- Linsight task_exec uses session_model.tenant_id -----------------------


def test_linsight_task_exec_threads_session_tenant():
    src = _read('linsight/domain/task_exec.py')
    # _get_llm now takes tenant_id; called from _execute_workflow.
    assert 'tenant_id=session_model.tenant_id' in src
    assert 'tenant_id: Optional[int]' in src


# --- Resource-scenario sites use owner tenant_id ---------------------------


def test_evaluation_uses_evaluation_tenant():
    src = _read('evaluation/domain/services/evaluation_service.py')
    assert 'tenant_id=evaluation.tenant_id' in src


def test_file_encoding_uses_knowledge_file_tenant():
    src = _read('knowledge/rag/pipeline/transformer/file_encoding.py')
    assert "getattr(self.knowledge_file, 'tenant_id', None)" in src
    assert 'get_workbench_llm(tenant_id=tenant_id)' in src


def test_abstract_transformer_uses_knowledge_file_tenant():
    src = _read('knowledge/rag/pipeline/transformer/abstract.py')
    assert "getattr(self.knowledge_file, 'tenant_id', None)" in src
    assert 'tenant_id=tenant_id' in src


# --- knowledge_imp helpers accept tenant_id --------------------------------


def test_recommend_question_accepts_tenant_id():
    """``decide_knowledge_llm`` / ``async_decide_knowledge_llm`` were
    dead code (no callers) and were removed during /simplify cleanup;
    the live ``recommend_question`` consumer is what we still verify."""
    src = _read('api/services/knowledge_imp.py')
    assert 'def recommend_question(invoke_user_id: int, question: str, answer: str, number: int = 3,' in src
    assert 'tenant_id=tenant_id' in src
    assert 'def decide_knowledge_llm(' not in src
    assert 'def async_decide_knowledge_llm(' not in src


def test_knowledge_utils_abstract_llm_accepts_tenant_id():
    src = _read('knowledge/domain/services/knowledge_utils.py')
    assert 'def get_knowledge_abstract_llm(' in src
    assert 'tenant_id: Optional[int] = None' in src


# --- LLMService helpers accept tenant_id -----------------------------------


def test_llm_service_helpers_accept_tenant_id():
    src = _read('llm/domain/services/llm.py')
    # 5 helpers updated in Pass A
    assert 'def get_knowledge_source_llm(\n        cls, invoke_user_id: int, tenant_id: Optional[int] = None,' in src
    assert 'def get_knowledge_source_llm_async(\n        cls, invoke_user_id: int, tenant_id: Optional[int] = None,' in src
    assert 'def get_knowledge_similar_llm(\n        cls, invoke_user_id: int, tenant_id: Optional[int] = None,' in src
    assert 'def get_knowledge_default_embedding(\n        cls, invoke_user_id: int, tenant_id: Optional[int] = None,' in src
    assert 'def get_evaluation_llm_object(\n        cls, invoke_user_id: int, tenant_id: Optional[int] = None,' in src
