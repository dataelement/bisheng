import io
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from starlette.datastructures import UploadFile

from bisheng.common.errcode.finetune import TaskUploadExpiredError
from bisheng.finetune.domain.services import task_uploads
from bisheng.finetune.domain.services.task_uploads import TaskUploadService


@pytest.fixture
def upload_environment(monkeypatch):
    values = {}

    async def aset(key, value, expiration):
        values[key] = value

    cache = SimpleNamespace(aset=aset, aget=AsyncMock(side_effect=lambda key: values.get(key)))
    storage = SimpleNamespace(bucket="test", put_object=AsyncMock())
    monkeypatch.setattr(task_uploads, "get_current_tenant_id", lambda: 7)
    monkeypatch.setattr(task_uploads, "get_redis_client", AsyncMock(return_value=cache))
    monkeypatch.setattr(task_uploads, "get_minio_storage", AsyncMock(return_value=storage))
    return values, storage


async def test_temporary_upload_is_bound_to_user_and_does_not_write_dataset_tables(upload_environment, monkeypatch):
    from bisheng.finetune.domain.repositories.dataset import FinetuneDatasetRepository
    from bisheng.finetune.domain.repositories.dataset_catalog import DatasetCatalogRepository

    save_version, save_catalog = AsyncMock(), AsyncMock()
    monkeypatch.setattr(FinetuneDatasetRepository, "save", save_version)
    monkeypatch.setattr(DatasetCatalogRepository, "save", save_catalog)
    payload = json.dumps(
        [{"messages": [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}]}]
    ).encode()
    file = UploadFile(io.BytesIO(payload), filename="test.json", size=len(payload))
    user = SimpleNamespace(user_id=3, user_name="tester")
    result = await TaskUploadService.upload(file, user)
    assert result["temporary"] and result["dataset_report"]["data_type"] == "text"
    assert (await TaskUploadService.resolve(result["upload_id"], user))["url"] == result["url"]
    with pytest.raises(TaskUploadExpiredError):
        await TaskUploadService.resolve(result["upload_id"], SimpleNamespace(user_id=4))
    save_version.assert_not_called()
    save_catalog.assert_not_called()
    upload_environment[0].clear()
    with pytest.raises(TaskUploadExpiredError):
        await TaskUploadService.resolve(result["upload_id"], user)
