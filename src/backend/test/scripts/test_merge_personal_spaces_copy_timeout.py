"""复制写入与刷新使用迁移超时, 失败报告保留原始原因。"""

import ast
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from elastic_transport import ConnectionTimeout

from test.scripts.test_merge_personal_knowledge_spaces import file, m, space


@pytest.mark.parametrize("failed", [False, True])
async def test_copy_es_timeout_and_failure_details(monkeypatch, failed):
    file_worker = import_module("bisheng.worker.knowledge.file_worker")
    source = file()
    target_file = source.model_copy(update={"id": 126812, "knowledge_id": 20})
    tuned_client = SimpleNamespace(indices=SimpleNamespace(refresh=Mock()))
    client = SimpleNamespace(options=Mock(return_value=tuned_client))
    store = SimpleNamespace(client=client)
    # conftest 替换了整个 worker 模块, 这里装载真实写入函数以覆盖实际调用契约。
    worker_path = Path(m.__file__).parents[1] / "bisheng/worker/knowledge/file_worker.py"
    tree = ast.parse(worker_path.read_text())
    insert_node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "insert_es")
    namespace = {"generate_uuid": lambda: "chunk-id", "logger": Mock()}
    exec("from __future__ import annotations\n" + ast.unparse(insert_node), namespace)
    original_insert = namespace["insert_es"]
    monkeypatch.setattr(file_worker, "insert_es", original_insert, raising=False)
    monkeypatch.setattr(m, "_target_preview_object_name", lambda *args: "preview/126812.pdf")

    def bulk(actual_client, actions):
        assert actual_client is tuned_client
        assert actions[0]["metadata"]["document_id"] == 126812
        if failed:
            raise ConnectionTimeout("copy bulk timed out")

    monkeypatch.setattr("elasticsearch.helpers.bulk", bulk)

    def copy_normal(*args, **kwargs):
        try:
            file_worker.insert_es([{"text": "content", "vector": [1.0], "document_id": 126812}], store, "target-index")
        except ConnectionTimeout as exc:
            target_file.status = 3
            target_file.remark = str(exc)
        return target_file

    monkeypatch.setattr(m, "copy_normal", copy_normal)
    monkeypatch.setattr(m.KnowledgeFileDao, "async_update", AsyncMock(return_value=target_file))
    operations = m.GuardedOperations(1, {10: space()})
    operations.snapshots[source.id] = m.SourceSnapshot(m.TagSnapshot(), (), m.IndexSnapshot(1, 1), {})
    target = m.TargetContext(1, space(20), None, SimpleNamespace(user_id=7, user_name="test"), "", 0)
    if failed:
        with pytest.raises(m.TargetCopyError, match="copy_failure=Connection timed out") as error:
            await operations.copy_file(source, target)
        assert error.value.target_file is target_file
        tuned_client.indices.refresh.assert_not_called()
        delete_indexes = Mock()
        monkeypatch.setattr(m, "delete_vector_files", delete_indexes)
        monkeypatch.setattr(m, "delete_minio_files", Mock())
        monkeypatch.setattr(m, "_clear_tag_links", AsyncMock())
        monkeypatch.setattr(m, "_replace_permission_tuples", AsyncMock())
        monkeypatch.setattr(m.KnowledgeFileDao, "delete_batch", Mock())
        cleanup_errors = await operations.cleanup_target(target_file, target)
        assert "preserved" in cleanup_errors[0]
        delete_indexes.assert_not_called()
        m.delete_minio_files.assert_not_called()
        m.KnowledgeFileDao.delete_batch.assert_not_called()
    else:
        assert await operations.copy_file(source, target) is target_file
        tuned_client.indices.refresh.assert_called_once_with(index="target-index")
    client.options.assert_called_once_with(request_timeout=60, max_retries=0, retry_on_timeout=False)
    assert file_worker.insert_es is original_insert
    assert store.client is client
