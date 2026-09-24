"""空间初始化只校验已配置的共享存储, 不再创建独立索引。"""

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
from bisheng.knowledge.rag import shared_space_storage as storage


@pytest.mark.parametrize("exists", [True, False])
def test_space_initialization_checks_shared_target(monkeypatch, exists):
    monkeypatch.setitem(sys.modules, "bisheng.worker._asyncio_utils", SimpleNamespace(run_async_task=MagicMock()))
    monkeypatch.setitem(sys.modules, "bisheng.worker.main", SimpleNamespace(
        bisheng_celery=SimpleNamespace(task=lambda **_: lambda f: f),
    ))
    spec = importlib.util.spec_from_file_location(
        "space_init_under_test", Path(__file__).parents[2] / "bisheng/worker/knowledge/space_init_worker.py"
    )
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    knowledge = SimpleNamespace(type=KnowledgeTypeEnum.SPACE.value, tenant_id=7)
    monkeypatch.setattr(worker.KnowledgeDao, "query_by_id", lambda _: knowledge)
    legacy = MagicMock(side_effect=AssertionError("SPACE cannot initialize legacy storage"))
    monkeypatch.setattr(worker.KnowledgeRag, "init_knowledge_milvus_vectorstore_sync", legacy)
    route = SimpleNamespace(index_name="shared_text_7")
    monkeypatch.setattr(storage, "load_tenant_routing_snapshot", lambda _: route)
    monkeypatch.setattr(storage, "require_initialized_shared_routing", lambda _, value: value)
    client = MagicMock()
    client.indices.exists.return_value = exists
    factory = MagicMock(return_value=(SimpleNamespace(es_client=client), object()))
    monkeypatch.setattr(storage, "build_shared_space_components_for_tenant", factory)
    if exists:
        assert "shared" in worker.init_knowledge_space_indices(12, 5)
    else:
        with pytest.raises(storage.SharedStorageContractError):
            worker.init_knowledge_space_indices(12, 5)
    factory.assert_called_once()
    client.indices.exists.assert_called_once_with(index="shared_text_7")
    client.indices.create.assert_not_called()
    client.close.assert_called_once()
    legacy.assert_not_called()
