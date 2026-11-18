"""Old overwrite clients cannot move a file through content retry."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao
from test.knowledge_unification.test_file_worker import source_module


@pytest.fixture
def retry(monkeypatch):
    from bisheng.worker.knowledge import file_worker

    storage = AsyncMock()
    update = AsyncMock(side_effect=lambda row: row)
    task = Mock()
    monkeypatch.setattr("bisheng.core.storage.minio.minio_manager.get_minio_storage", storage)
    monkeypatch.setattr(KnowledgeFileDao, "async_update", update)
    monkeypatch.setattr(file_worker, "retry_knowledge_file_celery", task)
    import bisheng.common.services.base as base

    backend = Path(__file__).resolve().parents[2]
    monkeypatch.setattr(
        base,
        "BaseService",
        source_module("_retry_actual_base", backend / "bisheng/common/services/base.py").BaseService,
    )
    utils = source_module(
        "_retry_actual_utils", backend / "bisheng/knowledge/domain/services/knowledge_utils.py"
    ).KnowledgeUtils
    monkeypatch.setattr(utils, "preview_cache_key_for_split_rule", lambda *args: "preview")
    return SimpleNamespace(storage=storage, update=update, task=task, utils=utils)


def file(ident=1, path="/10"):
    return SimpleNamespace(
        id=ident,
        knowledge_id=7,
        file_name="x.pdf",
        object_name="obj/x",
        file_level_path=path,
        level=1 if path else 0,
        split_rule="{}",
        status=3,
    )


@pytest.mark.parametrize("path", ["/20", "", "/10/30"])
async def test_whole_batch_rejects_changed_directory_before_any_side_effect(retry, path):
    first, second = file(), file(2)
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await retry.utils.process_retry_files(
            [first, second],
            {1: {"split_rule": "{}"}, 2: {"split_rule": "{}", "file_level_path": path}},
            SimpleNamespace(user_id=5, user_name="operator"),
        )
    assert first.status == second.status == 3
    assert first.file_level_path == second.file_level_path == "/10"
    retry.storage.assert_not_awaited()
    retry.update.assert_not_awaited()
    retry.task.delay.assert_not_called()


@pytest.mark.parametrize("path", ["/10", None])
async def test_retry_keeps_directory_level_and_clears_content_similarity(retry, path):
    row = file(path=path or "")
    request = {"split_rule": "{}", "remark": "{}"}
    if path is not None:
        request["file_level_path"] = path
    result, parents = await retry.utils.process_retry_files(
        [row], {1: request}, SimpleNamespace(user_id=5, user_name="operator")
    )
    assert result == [row] and parents == ({path} if path else set())
    assert row.file_level_path == (path or "") and row.level == (1 if path else 0)
    assert row.status == 5 and row.similar_status == 0 and row.simhash is None
    retry.update.assert_awaited_once_with(row)
    retry.task.delay.assert_called_once_with(1, "preview", None)
