import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import zipfile

import pytest
from fastapi import UploadFile

from bisheng.common.errcode.knowledge import KnowledgeArchiveUploadError
from bisheng.knowledge.domain.services.archive_upload_service import ArchiveUploadService as Service


def upload():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("合同/一.txt", "合同金额100元")
        z.writestr("财务/一.txt", "财务金额200元")
    stream.seek(0)
    return UploadFile(filename="资料.zip", file=stream)


class Store:
    tmp_bucket = "tmp"
    def __init__(self, fail=None):
        self.objects = {}
        self.fail = fail
        self.removed = []

    async def put_object(self, *, object_name, file, **kwargs):
        self.objects[object_name] = file.read_bytes() if isinstance(file, Path) else file
        if self.fail and self.fail in object_name:
            raise OSError("storage failed after write")

    async def remove_object(self, *, object_name, **kwargs):
        self.removed.append(object_name)
        self.objects.pop(object_name, None)

    async def get_share_link(self, object_name, **kwargs):
        return f"/tmp/{object_name}?X-Amz-Algorithm=test"


@pytest.fixture
def infrastructure(monkeypatch):
    import bisheng.knowledge.domain.services.archive_upload_service as module
    store = Store()
    connection = SimpleNamespace(set=AsyncMock(return_value=True), eval=AsyncMock(return_value=1))
    monkeypatch.setattr(module, "get_max_upload_bytes", lambda _: 50*1024*1024)
    monkeypatch.setattr(module, "get_current_tenant_id", lambda: 2)
    monkeypatch.setattr(module, "get_redis_client", AsyncMock(return_value=SimpleNamespace(async_connection=connection)))
    monkeypatch.setattr(module, "get_minio_storage", AsyncMock(return_value=store))
    return module, store, connection


async def test_upload_manifest_and_uuid_namespace(infrastructure):
    module, store, connection = infrastructure
    result = await Service.upload(upload(), 7, ".txt,.zip")
    assert len(result["files"]) == 2
    assert result["files"][0]["display_name"] == "资料.zip/合同/一.txt"
    assert result["files"][0]["relative_path"].startswith(result["archive_id"]+"/合同/")
    manifest = json.loads(next(v for k,v in store.objects.items() if k.endswith("manifest.json")))
    assert manifest["user_id"] == 7 and manifest["tenant_id"] == 2
    assert len({f["file_id"] for f in result["files"]}) == 2
    connection.set.assert_awaited_once()
    connection.eval.assert_awaited_once()


async def test_manifest_failure_rolls_back_uncertain_writes(infrastructure):
    _, store, connection = infrastructure
    store.fail = "manifest.json"
    with pytest.raises(OSError):
        await Service.upload(upload(), 7, ".txt")
    assert not store.objects
    assert len(store.removed) == 3
    connection.eval.assert_awaited_once()


async def test_busy_lock_is_not_deleted(infrastructure):
    _, store, connection = infrastructure
    connection.set.return_value = False
    with pytest.raises(KnowledgeArchiveUploadError):
        await Service.upload(upload(), 7, ".txt")
    connection.eval.assert_not_awaited()
    assert not store.objects


async def test_invalid_archive_leaves_no_objects_and_releases_lock(infrastructure):
    _, store, connection = infrastructure
    file = UploadFile(filename="bad.zip", file=io.BytesIO(b"not a zip"))
    with pytest.raises(KnowledgeArchiveUploadError):
        await Service.upload(file, 7, ".txt")
    assert not store.objects
    connection.eval.assert_awaited_once()


def test_owner_and_tenant_are_checked_before_storage(infrastructure):
    module, _, _ = infrastructure
    with pytest.raises(KnowledgeArchiveUploadError):
        Service.source_info('/tmp/archive-upload/2/8/'+ 'a'*32 +'/'+'b'*32+'.txt', 7)
    with pytest.raises(KnowledgeArchiveUploadError):
        Service.source_info('/tmp/archive-upload/3/7/'+ 'a'*32 +'/'+'b'*32+'.txt', 7)


def test_manifest_resolution_and_expired_redis_are_independent(infrastructure, monkeypatch):
    module, _, _ = infrastructure
    key = 'archive-upload/2/7/'+'a'*32+'/'+'b'*32+'.txt'
    row = {"object_name":key,"display_name":"资料.zip/合同/一.txt","size":9}
    sync_store = SimpleNamespace(tmp_bucket="tmp", get_object_sync=MagicMock(return_value=json.dumps({"files":[row]}).encode()))
    monkeypatch.setattr(module,"get_minio_storage_sync",lambda:sync_store)
    assert Service.source_info('/tmp/'+key+'?signature=x',7) == row


def test_combined_count_limit(infrastructure, monkeypatch):
    monkeypatch.setattr(Service,"source_info",staticmethod(lambda ref,user: {"size":1} if ref=='zip-child' else None))
    with pytest.raises(KnowledgeArchiveUploadError):
        Service.validate_references(['zip-child']+['normal']*20,7)


def test_ordinary_files_keep_existing_behavior(infrastructure):
    assert Service.validate_references(['https://local/file.pdf'],7) == {}
