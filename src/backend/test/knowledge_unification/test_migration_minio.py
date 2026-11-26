"""Raw MinIO adapter never initializes buckets/policies or reads file bodies."""

import hashlib
import importlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import miniopy_async
import pytest
from miniopy_async.error import S3Error

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.config.settings import MinioConf
from bisheng.knowledge.application.unification_artifacts import UnificationArtifactStore


@pytest.fixture
def module():
    return importlib.import_module("bisheng.knowledge.application.unification_minio")


@pytest.fixture
def raw():
    client = miniopy_async.Minio("private.invalid:9000", access_key="test-user", secret_key="test-only", secure=False)
    client._execute = AsyncMock(return_value=SimpleNamespace(headers={"content-length": "12", "etag": '"opaque"'}))
    return client


def storage(module, raw):
    return module.UnificationMinio(client=raw, bucket="private-facts", tmp_bucket="temporary")


def artifact():
    value = {"schema_version": 1, "run_id": "r-1", "kind": "baseline", "records": []}
    content = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    key = f"f118/unification/r-1/baseline/{hashlib.sha256(content).hexdigest()}.json"
    return key, content


def failure(code):
    return S3Error(code, "private details", "private key", "request", "host", SimpleNamespace(status=404))


async def test_exact_original_key_uses_real_native_head_without_tenant_fallback(module, raw):
    adapter = storage(module, raw)
    assert await adapter.astat_object("tenant_original/original/81.txt") == {
        "exists": True,
        "size": 12,
        "etag": "opaque",
    }
    raw._execute.assert_awaited_once()
    call = raw._execute.call_args
    assert call.args[:3] == ("HEAD", "private-facts", "tenant_original/original/81.txt")
    assert "test-only" not in repr(adapter)


@pytest.mark.parametrize("code", ["NoSuchKey", "AccessDenied", "NoSuchBucket", "SlowDown"])
async def test_only_native_no_such_key_becomes_missing(module, raw, code):
    raw._execute.side_effect = failure(code)
    adapter = storage(module, raw)
    if code == "NoSuchKey":
        assert await adapter.astat_object("original/81.txt") == {"exists": False, "size": None, "etag": None}
    else:
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await adapter.astat_object("original/81.txt")
    assert raw._execute.await_count == 1


@pytest.mark.parametrize("key", ["", "/absolute", "../escape", "original/../escape", "https://host/key", "a\x00b"])
async def test_unsafe_physical_key_fails_before_native_call(module, raw, key):
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await storage(module, raw).astat_object(key)
    raw._execute.assert_not_awaited()


async def test_negative_native_size_is_not_a_valid_existence_fact(module, raw):
    raw._execute.return_value.headers["content-length"] = "-1"
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await storage(module, raw).astat_object("original/81.txt")


class Response:
    def __init__(self, content, *, declared=None):
        self.data = content
        self.headers = {} if declared is None else {"content-length": str(declared)}
        self.content = self
        self.release = Mock()
        self.chunks = 0

    async def iter_chunked(self, size):
        for start in range(0, len(self.data), size):
            self.chunks += 1
            yield self.data[start : start + size]


async def test_actual_artifact_store_can_put_and_verify_with_native_minio_get_put(module, raw):
    key, content = artifact()
    response = Response(content, declared=len(content))
    raw.stat_object = AsyncMock(side_effect=[failure("NoSuchKey")])
    raw.put_object = AsyncMock()
    raw.get_object = AsyncMock(return_value=response)
    adapter = storage(module, raw)
    store = UnificationArtifactStore(adapter)
    descriptor = await store.aput_canonical(run_id="r-1", kind="baseline", content=content)
    assert descriptor == {"object_key": key, "sha256": hashlib.sha256(content).hexdigest()}
    call = raw.put_object.call_args.kwargs
    assert call["bucket_name"] == "private-facts" and call["object_name"] == key
    assert call["data"].getvalue() == content and call["length"] == len(content)
    assert call["content_type"] == "application/json"
    response.release.assert_called_once()


@pytest.mark.parametrize("declared", [None, 16 * 1024 * 1024 + 1])
async def test_oversized_artifact_is_rejected_and_response_always_released(module, raw, declared):
    key, _ = artifact()
    response = Response(b"x" * (16 * 1024 * 1024 + 1), declared=declared)
    raw.get_object = AsyncMock(return_value=response)
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await storage(module, raw).get_object(bucket_name="private-facts", object_name=key)
    response.release.assert_called_once()
    assert response.chunks <= 257


@pytest.mark.parametrize("operation", ["get", "put", "exists"])
async def test_artifacts_never_use_temporary_bucket_or_non_content_addressed_path(module, raw, operation):
    key, content = artifact()
    adapter = storage(module, raw)
    for bucket, name in (("temporary", key), ("private-facts", "original/private.txt")):
        with pytest.raises(KnowledgeOperationPlanConflictError):
            if operation == "get":
                await adapter.get_object(bucket_name=bucket, object_name=name)
            elif operation == "put":
                await adapter.put_object(bucket_name=bucket, object_name=name, file=content)
            else:
                await adapter.object_exists(bucket_name=bucket, object_name=name)
    raw._execute.assert_not_awaited()


async def test_content_address_mismatch_refused_before_write(module, raw):
    key, _ = artifact()
    raw.put_object = AsyncMock()
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await storage(module, raw).put_object(bucket_name="private-facts", object_name=key, file=b"other")
    raw.put_object.assert_not_awaited()


async def test_native_factory_owns_session_without_generic_storage_initialization(module, monkeypatch):
    from bisheng.core.storage.minio.minio_storage import MinioStorage

    generic = Mock(side_effect=AssertionError("must not create buckets or mutate policies"))
    monkeypatch.setattr(MinioStorage, "__init__", generic)
    conf = MinioConf(endpoint="private.invalid:9000", access_key="test", secret_key="private-secret")
    async with module.UnificationMinio.aopen(conf) as adapter:
        session = adapter._session
        assert not session.closed
        assert isinstance(adapter._client, miniopy_async.Minio)
        assert "private-secret" not in repr(adapter)
    assert session.closed
    generic.assert_not_called()
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await adapter.astat_object("original/81.txt")
