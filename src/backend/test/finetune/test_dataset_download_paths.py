"""Browser downloads must use the object proxy without changing signed queries."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import urlsplit

import pytest

from bisheng.core.storage.minio.minio_storage import MinioStorage
from bisheng.finetune.domain.repositories.dataset_catalog import DatasetCatalogRepository
from bisheng.finetune.domain.repositories.file_download_repository import FileDownloadRepository
from bisheng.finetune.domain.services import datasets, finetune_file
from bisheng.knowledge.domain.services.preview_source_service import PreviewSourceService


class SignedStorage:
    bucket = "bisheng"
    tmp_bucket = "staging"
    get_share_link = MinioStorage.get_share_link
    get_share_link_sync = MinioStorage.get_share_link_sync
    get_minio_share_host = MinioStorage.get_minio_share_host
    clear_minio_share_host = MinioStorage.clear_minio_share_host

    def __init__(self, key):
        self.minio_config = SimpleNamespace(sharepoint="storage.example:9102", share_schema=False)
        self.share_minio_client = MagicMock()
        self.share_minio_client.presigned_get_object.return_value = (
            f"http://storage.example:9102/bisheng/{key}?X-Amz-Signature=test&X-Amz-SignedHeaders=host"
        )


@pytest.mark.parametrize("entry", ["catalog", "legacy_catalog", "owned_training_file"])
async def test_browser_dataset_download_uses_object_route_and_preserves_signature(monkeypatch, entry):
    key = "dataset/train.json" if entry != "owned_training_file" else "finetune/train_file/personal/7/11/train.json"
    storage = SignedStorage(key)
    monkeypatch.setattr(datasets, "get_minio_storage", AsyncMock(return_value=storage))
    monkeypatch.setattr(finetune_file, "get_minio_storage", AsyncMock(return_value=storage))
    catalog = SimpleNamespace(id="catalog", version_id=None, url=key)
    monkeypatch.setattr(DatasetCatalogRepository, "find", AsyncMock(return_value=catalog))
    monkeypatch.setattr(
        DatasetCatalogRepository,
        "find_url",
        AsyncMock(return_value=None if entry == "owned_training_file" else catalog),
    )
    monkeypatch.setattr(PreviewSourceService, "is_owned_object", AsyncMock(return_value=True))
    monkeypatch.setattr(FileDownloadRepository, "preset_by_object", AsyncMock(return_value=None))
    if entry == "catalog":
        url = (await datasets.DatasetService.download_catalog("catalog"))["url"]
    else:
        url = await finetune_file.FinetuneFileService.get_download_url(key, SimpleNamespace(user_id=11, tenant_id=7))
    assert urlsplit(url).path == f"/object/bisheng/{key}"
    assert not urlsplit(url).netloc
    assert urlsplit(url).query == "X-Amz-Signature=test&X-Amz-SignedHeaders=host"
