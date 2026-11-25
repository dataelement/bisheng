"""Object existence must never authorize a browser presign refresh."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.workstation.api.endpoints import knowledge as endpoint


@pytest.mark.parametrize(
    "path", ["/tmp-dir/victim.txt", "/bisheng/original/1.pdf", "/tmp-dir/victim.txt?X-Amz-Signature=old"]
)
async def test_foreign_object_denied_before_storage_sdk(monkeypatch, path):
    storage = SimpleNamespace(
        bucket="bisheng",
        tmp_bucket="tmp-dir",
        object_exists=AsyncMock(return_value=True),
        get_share_link=AsyncMock(return_value="signed"),
    )
    monkeypatch.setattr(endpoint, "get_minio_storage", AsyncMock(return_value=storage))
    # The actual owned-object service denies absent caller-bound evidence.
    from bisheng.knowledge.domain.services.preview_source_service import PreviewSourceService

    monkeypatch.setattr(PreviewSourceService, "is_owned_object", AsyncMock(return_value=False), raising=False)
    with pytest.raises(UnAuthorizedError):
        await endpoint.get_file_share_url(filepath=path, login_user=SimpleNamespace(user_id=11, tenant_id=7))
    storage.object_exists.assert_not_awaited()
    storage.get_share_link.assert_not_awaited()


async def test_bound_upload_refreshes_expired_signature(monkeypatch):
    from bisheng.knowledge.domain.services.preview_source_service import PreviewSourceService

    storage = SimpleNamespace(
        bucket="bisheng",
        tmp_bucket="tmp-dir",
        object_exists=AsyncMock(return_value=True),
        get_share_link=AsyncMock(return_value="signed"),
    )
    monkeypatch.setattr(endpoint, "get_minio_storage", AsyncMock(return_value=storage))
    owned = AsyncMock(return_value=True)
    monkeypatch.setattr(PreviewSourceService, "is_owned_object", owned)
    result = await endpoint.get_file_share_url(
        filepath="/tmp-dir/workstation/7/11/file.pdf?X-Amz-Signature=old",
        login_user=SimpleNamespace(user_id=11, tenant_id=7),
    )
    assert result.data == {"url": "signed"}
    storage.get_share_link.assert_awaited_once_with("workstation/7/11/file.pdf", bucket="tmp-dir")


@pytest.mark.parametrize("key", ["a/../b", "a/%252e%252e/b", "a\\b", "a//b"])
def test_key_canonicalization_denies_traversal(key):
    from bisheng.workstation.domain.services.object_download_service import canonical_object_key

    with pytest.raises(UnAuthorizedError):
        canonical_object_key(key)


@pytest.mark.parametrize("row_tenant,allowed", [(7, True), (8, False)])
async def test_persisted_chat_reference_requires_real_owner_tenant(monkeypatch, row_tenant, allowed):
    from bisheng.knowledge.domain.services.preview_source_service import PreviewSourceService
    from bisheng.workstation.domain.repositories.object_download_repository import ObjectDownloadRepository
    from bisheng.workstation.domain.services.object_download_service import ObjectDownloadService

    monkeypatch.setattr(PreviewSourceService, "is_owned_object", AsyncMock(return_value=False))
    monkeypatch.setattr(
        ObjectDownloadRepository,
        "owned_attachment_rows",
        AsyncMock(
            return_value=[
                SimpleNamespace(user_id=11, tenant_id=row_tenant, files='[{"object_name":"chat/11/file.pdf"}]')
            ]
        ),
    )
    storage = SimpleNamespace(bucket="bisheng", tmp_bucket="tmp-dir")
    if allowed:
        await ObjectDownloadService.require_owned(
            "bisheng", "chat/11/file.pdf", SimpleNamespace(user_id=11, tenant_id=7), storage
        )
    else:
        with pytest.raises(UnAuthorizedError):
            await ObjectDownloadService.require_owned(
                "bisheng", "chat/11/file.pdf", SimpleNamespace(user_id=11, tenant_id=7), storage
            )


async def test_workstation_upload_registers_server_selected_owned_key(monkeypatch):
    from unittest.mock import MagicMock

    from bisheng.knowledge.domain.services.preview_source_service import PreviewSourceService

    storage = SimpleNamespace(
        bucket="bisheng",
        tmp_bucket="tmp-dir",
        minio_config=SimpleNamespace(endpoint="test"),
        clear_minio_share_host=lambda value: value,
    )
    monkeypatch.setattr(endpoint, "get_minio_storage", AsyncMock(return_value=storage))
    monkeypatch.setattr(endpoint, "MediaUploadStageTimer", MagicMock())
    upload = AsyncMock(side_effect=lambda file, folder, key: "/tmp-dir/" + key)
    monkeypatch.setattr(endpoint, "save_uploaded_file", upload)
    bind = AsyncMock()
    monkeypatch.setattr(PreviewSourceService, "bind_owned_object", bind)
    actor = SimpleNamespace(user_id=11, tenant_id=7)
    result = await endpoint.upload_file(
        None,
        file=SimpleNamespace(filename="../../document.pdf", content_type="application/pdf", close=AsyncMock()),
        file_id="client-id",
        login_user=actor,
    )
    key = upload.await_args.args[2]
    assert key.startswith("workstation/7/11/") and key.endswith(".pdf")
    assert "document" not in key
    bind.assert_awaited_once_with(bucket="tmp-dir", object_name=key, login_user=actor)
    assert result.data["filepath"] == "/tmp-dir/" + key


async def test_registry_binds_exact_user_tenant_bucket_and_key(monkeypatch):
    from bisheng.knowledge.domain.services import preview_source_service as registry

    data = {}

    async def aset(key, value, **kwargs):
        data[key] = value

    redis = SimpleNamespace(aset=aset, aget=AsyncMock(side_effect=lambda key: data.get(key)))
    monkeypatch.setattr(registry, "get_redis_client", AsyncMock(return_value=redis))
    monkeypatch.setattr(registry, "get_current_tenant_id", lambda: None)
    actor = SimpleNamespace(user_id=11, tenant_id=7)
    await registry.PreviewSourceService.bind_owned_object(bucket="tmp-dir", object_name="own.pdf", login_user=actor)
    assert await registry.PreviewSourceService.is_owned_object(
        bucket="tmp-dir", object_name="own.pdf", login_user=actor
    )
    for other in [SimpleNamespace(user_id=12, tenant_id=7), SimpleNamespace(user_id=11, tenant_id=8)]:
        assert not await registry.PreviewSourceService.is_owned_object(
            bucket="tmp-dir", object_name="own.pdf", login_user=other
        )
    assert not await registry.PreviewSourceService.is_owned_object(
        bucket="bisheng", object_name="own.pdf", login_user=actor
    )
