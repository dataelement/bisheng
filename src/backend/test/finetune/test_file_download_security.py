"""Finetune download cannot sign unrelated bucket objects."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.finetune import TrainFileNotExistError
from bisheng.finetune.api import finetune as endpoint


async def test_arbitrary_key_denied_before_sdk(monkeypatch):
    storage = SimpleNamespace(bucket="bisheng", tmp_bucket="tmp-dir", get_share_link=AsyncMock(return_value="signed"))
    monkeypatch.setattr(endpoint, "get_minio_storage_sync", lambda: storage, raising=False)
    from bisheng.knowledge.domain.services.preview_source_service import PreviewSourceService

    monkeypatch.setattr(PreviewSourceService, "is_owned_object", AsyncMock(return_value=False), raising=False)
    with pytest.raises(TrainFileNotExistError):
        await endpoint.get_download_url(file_url="original/1.pdf", login_user=SimpleNamespace(user_id=11, tenant_id=7))
    storage.get_share_link.assert_not_awaited()


async def test_fresh_personal_upload_and_download_share_owned_binding(monkeypatch):
    from bisheng.finetune.domain.repositories.file_download_repository import FileDownloadRepository
    from bisheng.finetune.domain.services import finetune_file as service
    from bisheng.knowledge.domain.services.preview_source_service import PreviewSourceService

    storage = SimpleNamespace(bucket="bisheng", put_object=AsyncMock(), get_share_link=AsyncMock(return_value="signed"))
    monkeypatch.setattr(service, "get_minio_storage", AsyncMock(return_value=storage))
    bind = AsyncMock()
    monkeypatch.setattr(PreviewSourceService, "bind_owned_object", bind)
    monkeypatch.setattr(PreviewSourceService, "is_owned_object", AsyncMock(return_value=True))
    monkeypatch.setattr(FileDownloadRepository, "preset_by_object", AsyncMock(return_value=None))
    actor = SimpleNamespace(user_id=11, tenant_id=7, user_name="u")
    uploaded = await service.FinetuneFileService.upload_file_to_minio(
        [SimpleNamespace(filename="../../train.json", file=object(), content_type="application/json", size=1)],
        "finetune/train_file/personal",
        actor,
    )
    key = uploaded[0].url
    assert key.startswith("finetune/train_file/personal/7/11/")
    assert key.endswith(".json")
    bind.assert_awaited_once_with(bucket="bisheng", object_name=key, login_user=actor)
    assert await service.FinetuneFileService.get_download_url(key, actor) == "signed"


@pytest.mark.parametrize("bound,record_tenant,allowed", [(False, 8, False), (False, 7, True), (True, None, True)])
async def test_download_checks_binding_or_tenant_owned_preset(monkeypatch, bound, record_tenant, allowed):
    from bisheng.finetune.domain.repositories.file_download_repository import FileDownloadRepository
    from bisheng.finetune.domain.services import finetune_file as service
    from bisheng.knowledge.domain.services.preview_source_service import PreviewSourceService

    storage = SimpleNamespace(bucket="bisheng", get_share_link=AsyncMock(return_value="signed"))
    monkeypatch.setattr(service, "get_minio_storage", AsyncMock(return_value=storage))
    monkeypatch.setattr(PreviewSourceService, "is_owned_object", AsyncMock(return_value=bound))
    monkeypatch.setattr(
        FileDownloadRepository,
        "preset_by_object",
        AsyncMock(return_value=(SimpleNamespace(tenant_id=record_tenant, user_id=11) if record_tenant else None)),
    )
    monkeypatch.setattr(FileDownloadRepository, "owned_jobs", AsyncMock(return_value=[]))
    actor = SimpleNamespace(user_id=11, tenant_id=7)
    if allowed:
        assert (
            await service.FinetuneFileService.get_download_url("finetune/train_file/preset/id.json", actor) == "signed"
        )
    else:
        with pytest.raises(TrainFileNotExistError):
            await service.FinetuneFileService.get_download_url("finetune/train_file/preset/id.json", actor)
        storage.get_share_link.assert_not_awaited()


async def test_global_admin_can_read_same_tenant_persisted_preset(monkeypatch):
    from bisheng.finetune.domain.repositories.file_download_repository import FileDownloadRepository
    from bisheng.finetune.domain.services import finetune_file as service
    from bisheng.knowledge.domain.services.preview_source_service import PreviewSourceService

    storage = SimpleNamespace(bucket="bisheng", get_share_link=AsyncMock(return_value="signed"))
    monkeypatch.setattr(service, "get_minio_storage", AsyncMock(return_value=storage))
    monkeypatch.setattr(PreviewSourceService, "is_owned_object", AsyncMock(return_value=False))
    monkeypatch.setattr(
        FileDownloadRepository, "preset_by_object", AsyncMock(return_value=SimpleNamespace(tenant_id=7, user_id=22))
    )
    assert (
        await service.FinetuneFileService.get_download_url(
            "finetune/train_file/preset/id.json", SimpleNamespace(user_id=11, tenant_id=7, is_admin=lambda: True)
        )
        == "signed"
    )


@pytest.mark.parametrize(
    "key,allowed",
    [
        ("finetune/train_file/personal/7/11/id.json", True),
        ("finetune/train_file/personal/8/11/id.json", False),
        ("finetune/train_file/personal/legacy.json", False),
    ],
)
async def test_expired_registry_needs_scoped_actual_job(monkeypatch, key, allowed):
    from bisheng.finetune.domain.repositories.file_download_repository import FileDownloadRepository
    from bisheng.finetune.domain.services import finetune_file as service
    from bisheng.knowledge.domain.services.preview_source_service import PreviewSourceService

    storage = SimpleNamespace(bucket="bisheng", get_share_link=AsyncMock(return_value="signed"))
    monkeypatch.setattr(service, "get_minio_storage", AsyncMock(return_value=storage))
    monkeypatch.setattr(PreviewSourceService, "is_owned_object", AsyncMock(return_value=False))
    monkeypatch.setattr(FileDownloadRepository, "preset_by_object", AsyncMock(return_value=None))
    monkeypatch.setattr(
        FileDownloadRepository,
        "owned_jobs",
        AsyncMock(return_value=[SimpleNamespace(tenant_id=7, train_data=[{"url": key}], preset_data=[])]),
    )
    actor = SimpleNamespace(user_id=11, tenant_id=7)
    if allowed:
        assert await service.FinetuneFileService.get_download_url(key, actor) == "signed"
    else:
        with pytest.raises(TrainFileNotExistError):
            await service.FinetuneFileService.get_download_url(key, actor)
        storage.get_share_link.assert_not_awaited()
