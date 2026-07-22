from __future__ import annotations

import asyncio
import hashlib
import shutil
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge_space import (
    PortalPdfArtifactUnavailableError,
    PortalPdfDownloadBusyError,
    PortalPdfDownloadGenerationError,
    PortalPdfDownloadServiceUnavailableError,
    PortalPdfDownloadTimeoutError,
    SpaceFileNotFoundError,
    SpacePermissionDeniedError,
)
from bisheng.core.config.settings import KnowledgePdfWatermarkConf
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFile
from bisheng.knowledge.domain.schemas.portal_pdf_download_schema import PortalPdfDownloadRequest
from bisheng.knowledge.domain.services.knowledge_pdf_artifact_service import PdfArtifactReference
from bisheng.knowledge.domain.services.pdf_artifact_on_demand_service import (
    PdfArtifactOnDemandGenerationError,
    PdfArtifactOnDemandTimeoutError,
)
from bisheng.knowledge.domain.services.portal_pdf_download_service import (
    PortalPdfDownloadProcessCapacity,
    PortalPdfDownloadService,
    PortalPdfDownloadUserLock,
)
from bisheng.knowledge.domain.services.portal_share_download_grant_service import (
    PortalShareDownloadGrantService,
)
from bisheng.knowledge.pdf.validator import validate_pdf
from bisheng.knowledge.pdf.watermark_worker import PdfWatermarkWorkerTimeout


def _pdf_bytes() -> bytes:
    document = fitz.open()
    document.new_page().insert_text((72, 72), "artifact source")
    data = document.tobytes()
    document.close()
    return data


_DEFAULT_PDF_BYTES = _pdf_bytes()


class FakeFileRepository:
    def __init__(self, file: KnowledgeFile | None) -> None:
        self.file = file

    async def find_by_id(self, file_id: int):
        return self.file if self.file and self.file.id == file_id else None


class FakeUserRepository:
    def __init__(self, user) -> None:
        self.user = user

    async def find_by_id(self, user_id: int):
        return self.user if self.user and self.user.user_id == user_id else None

    async def get_primary_department_name(self, user_id: int) -> str | None:
        if not self.user or self.user.user_id != user_id:
            return None
        return getattr(self.user, "primary_department_name", None)


class FakeAuthorizationService:
    def __init__(self, *, deny_normal: bool = False) -> None:
        self.deny_normal = deny_normal
        self.normal_calls: list[tuple[int, int]] = []
        self.share_calls: list[tuple[str, int, int]] = []

    async def require_shougang_portal_file_download_permission(self, *, space_id: int, file_id: int) -> None:
        self.normal_calls.append((space_id, file_id))
        if self.deny_normal:
            raise SpacePermissionDeniedError()

    async def require_shougang_portal_share_download(self, *, share_token: str, space_id: int, file_id: int) -> None:
        self.share_calls.append((share_token, space_id, file_id))


class FakeGrantService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def verify(self, token: str, **kwargs):
        self.calls.append({"token": token, **kwargs})
        return SimpleNamespace(share_token="share-token", allow_download=True)


class FakeStorageResponse:
    def __init__(self, payload: bytes, chunk_size: int = 97) -> None:
        self.payload = payload
        self.chunk_size = chunk_size
        self.offset = 0
        self.closed = False
        self.released = False

    def read(self, size: int = -1) -> bytes:
        if self.offset >= len(self.payload):
            return b""
        length = min(self.chunk_size, size if size > 0 else self.chunk_size)
        chunk = self.payload[self.offset : self.offset + length]
        self.offset += len(chunk)
        return chunk

    def close(self) -> None:
        self.closed = True

    def release_conn(self) -> None:
        self.released = True


class FakeStorage:
    def __init__(self, payload: bytes | None = None, payloads: list[bytes | Exception] | None = None) -> None:
        self.payload = _DEFAULT_PDF_BYTES if payload is None else payload
        self.payloads = list(payloads or [])
        self.requested_object_names: list[str] = []
        self.responses: list[FakeStorageResponse] = []

    def download_object_sync(self, *, object_name: str):
        self.requested_object_names.append(object_name)
        selected = self.payloads.pop(0) if self.payloads else self.payload
        if isinstance(selected, Exception):
            raise selected
        response = FakeStorageResponse(selected)
        self.responses.append(response)
        return response


class FakeUserLock:
    def __init__(self, token: str | None = "owner-token") -> None:
        self.token = token
        self.acquire_calls: list[tuple[int, int, int]] = []
        self.release_calls: list[tuple[int, int, str]] = []

    async def acquire(self, *, tenant_id: int, user_id: int, ttl_seconds: int):
        self.acquire_calls.append((tenant_id, user_id, ttl_seconds))
        return self.token

    async def release(self, *, tenant_id: int, user_id: int, token: str) -> None:
        self.release_calls.append((tenant_id, user_id, token))


class FakeArtifactEnsurer:
    def __init__(self, results: list[PdfArtifactReference | None | Exception]) -> None:
        self.results = list(results)
        self.calls: list[dict] = []

    async def __call__(self, file, *, invalid_generation=None, timeout_seconds=None):
        self.calls.append(
            {
                "file_id": file.id,
                "invalid_generation": invalid_generation,
                "timeout_seconds": timeout_seconds,
            }
        )
        result = self.results.pop(0) if len(self.results) > 1 else self.results[0]
        if isinstance(result, Exception):
            raise result
        return result


class CapturingRunner:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[dict] = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        shutil.copyfile(kwargs["input_path"], kwargs["output_path"])
        result = validate_pdf(kwargs["output_path"])
        return SimpleNamespace(page_count=result.page_count, artifact_size=result.artifact_size)


def _file(**overrides) -> KnowledgeFile:
    payload = {
        "id": 1580,
        "tenant_id": 5,
        "knowledge_id": 12,
        "file_name": "迁移指南.docx",
        "file_type": FileType.FILE.value,
    }
    payload.update(overrides)
    return KnowledgeFile(**payload)


def _artifact(**overrides) -> PdfArtifactReference:
    payload = {
        "tenant_id": 5,
        "knowledge_file_id": 1580,
        "generation": 1,
        "object_name": "knowledge/pdf-artifacts/1580/1/current.pdf",
        "artifact_sha256": hashlib.sha256(_DEFAULT_PDF_BYTES).hexdigest(),
        "page_count": 1,
        "artifact_size": len(_DEFAULT_PDF_BYTES),
        "completed_at": datetime.now(),
    }
    payload.update(overrides)
    return PdfArtifactReference(**payload)


def _user(**overrides):
    payload = {
        "user_id": 7,
        "user_name": "张三",
        "external_id": "SG001",
        "external_code": "CODE001",
        "primary_department_name": "设备管理部",
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def _login_user() -> UserPayload:
    return UserPayload(user_id=7, user_name="client-name-must-not-be-used", tenant_id=5)


def _request(**overrides) -> PortalPdfDownloadRequest:
    payload = {"space_id": 12, "file_id": 1580, "entry_point": "detail"}
    payload.update(overrides)
    return PortalPdfDownloadRequest(**payload)


_DEFAULT_ARTIFACT = object()


def _build_service(
    tmp_path: Path,
    *,
    file: KnowledgeFile | None = None,
    user=None,
    artifact: PdfArtifactReference | None | object = _DEFAULT_ARTIFACT,
    artifact_ensurer: FakeArtifactEnsurer | None = None,
    authorization: FakeAuthorizationService | None = None,
    storage: FakeStorage | None = None,
    user_lock: FakeUserLock | None = None,
    capacity: PortalPdfDownloadProcessCapacity | None = None,
    runner: CapturingRunner | None = None,
    telemetry: list | None = None,
    grant_service=None,
) -> tuple[PortalPdfDownloadService, dict]:
    selected_file = file if file is not None else _file()
    selected_user = user if user is not None else _user()
    selected_artifact = _artifact() if artifact is _DEFAULT_ARTIFACT else artifact
    selected_authorization = authorization or FakeAuthorizationService()
    selected_storage = storage or FakeStorage()
    selected_lock = user_lock or FakeUserLock()
    selected_capacity = capacity or PortalPdfDownloadProcessCapacity(2)
    selected_runner = runner or CapturingRunner()
    telemetry_events = telemetry if telemetry is not None else []

    selected_ensurer = artifact_ensurer or FakeArtifactEnsurer([selected_artifact])

    service = PortalPdfDownloadService(
        config=KnowledgePdfWatermarkConf(),
        file_repository=FakeFileRepository(selected_file),
        user_repository=FakeUserRepository(selected_user),
        authorization_service=selected_authorization,
        artifact_ensurer=selected_ensurer,
        artifact_readiness_timeout_seconds=300,
        storage=selected_storage,
        share_grant_service=grant_service or FakeGrantService(),
        user_lock=selected_lock,
        capacity_limiter=selected_capacity,
        watermark_runner=selected_runner,
        telemetry_recorder=telemetry_events.append,
        temp_root=tmp_path,
        now_provider=lambda: datetime(2026, 7, 21, 17, 30, 0),
    )
    return service, {
        "authorization": selected_authorization,
        "storage": selected_storage,
        "lock": selected_lock,
        "capacity": selected_capacity,
        "runner": selected_runner,
        "telemetry": telemetry_events,
        "grant": service.share_grant_service,
        "artifact_ensurer": selected_ensurer,
    }


@pytest.mark.asyncio
async def test_normal_download_uses_file_level_permission_and_current_artifact(tmp_path: Path) -> None:
    service, fakes = _build_service(tmp_path)

    prepared = await service.prepare_download(_request(), _login_user())

    assert fakes["authorization"].normal_calls == [(12, 1580)]
    assert fakes["authorization"].share_calls == []
    assert fakes["storage"].requested_object_names == ["knowledge/pdf-artifacts/1580/1/current.pdf"]
    assert fakes["storage"].responses[0].closed is True
    assert fakes["storage"].responses[0].released is True
    assert prepared.filename == "迁移指南.pdf"
    await prepared.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "object_name",
    [
        "tenant/5/knowledge/source/original.pdf",
        "tenant/5/knowledge/preview/1580.pdf",
        "knowledge/pdf-artifacts/1580/1/generated.pdf",
    ],
)
async def test_all_f063_artifact_origins_are_consumed_by_reference_without_copy_or_upload(
    tmp_path: Path,
    object_name: str,
) -> None:
    storage = FakeStorage()
    service, _ = _build_service(tmp_path, artifact=_artifact(object_name=object_name), storage=storage)

    prepared = await service.prepare_download(_request(), _login_user())

    assert storage.requested_object_names == [object_name]
    assert not hasattr(storage, "put_object_sync")
    await prepared.close()


@pytest.mark.asyncio
async def test_view_only_permission_is_rejected_before_artifact_read(tmp_path: Path) -> None:
    authorization = FakeAuthorizationService(deny_normal=True)
    storage = FakeStorage()
    service, _ = _build_service(tmp_path, authorization=authorization, storage=storage)

    with pytest.raises(SpacePermissionDeniedError):
        await service.prepare_download(_request(), _login_user())
    assert storage.requested_object_names == []


@pytest.mark.asyncio
async def test_share_download_uses_grant_and_live_recheck_without_normal_permission(tmp_path: Path) -> None:
    service, fakes = _build_service(tmp_path)
    request = _request(entry_point="share", share_access_grant="opaque-grant")

    prepared = await service.prepare_download(request, _login_user())

    assert fakes["authorization"].normal_calls == []
    assert fakes["authorization"].share_calls == [("share-token", 12, 1580)]
    assert fakes["grant"].calls[0]["token"] == "opaque-grant"
    await prepared.close()


@pytest.mark.asyncio
async def test_share_download_accepts_real_signed_grant_without_client_share_token(tmp_path: Path) -> None:
    grant_service = PortalShareDownloadGrantService(secret="unit-test-secret")
    issued = grant_service.issue(
        user_id=7,
        tenant_id=5,
        share_token="share-token",
        space_id=12,
        file_id=1580,
        allow_download=True,
    )
    service, fakes = _build_service(tmp_path, grant_service=grant_service)

    prepared = await service.prepare_download(
        _request(entry_point="share", share_access_grant=issued.token),
        _login_user(),
    )

    assert fakes["authorization"].share_calls == [("share-token", 12, 1580)]
    await prepared.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "file",
    [
        None,
        _file(knowledge_id=13),
        _file(tenant_id=6),
        _file(file_type=FileType.DIR.value),
    ],
)
async def test_file_space_tenant_and_type_must_match(tmp_path: Path, file) -> None:
    service, _ = _build_service(tmp_path, file=file if file is not None else _file(id=999))

    with pytest.raises(SpaceFileNotFoundError):
        await service.prepare_download(_request(), _login_user())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "artifact",
    [
        None,
        _artifact(tenant_id=6),
        _artifact(knowledge_file_id=1581),
        _artifact(object_name=""),
    ],
)
async def test_ensurer_final_unavailable_or_mismatched_artifact_fails_without_source_fallback(
    tmp_path: Path,
    artifact,
) -> None:
    storage = FakeStorage()
    service, _ = _build_service(
        tmp_path,
        artifact=artifact,
        storage=storage,
    )

    with pytest.raises(PortalPdfArtifactUnavailableError):
        await service.prepare_download(_request(), _login_user())
    assert storage.requested_object_names == []


@pytest.mark.asyncio
async def test_corrupt_success_artifact_is_repaired_once_then_downloaded(tmp_path: Path) -> None:
    first = _artifact(generation=1, object_name="knowledge/pdf-artifacts/1580/1/broken.pdf")
    repaired = _artifact(generation=2, object_name="knowledge/pdf-artifacts/1580/2/repaired.pdf")
    ensurer = FakeArtifactEnsurer([first, repaired])
    storage = FakeStorage(payloads=[b"not-a-pdf", _DEFAULT_PDF_BYTES])
    service, _ = _build_service(
        tmp_path,
        artifact_ensurer=ensurer,
        storage=storage,
    )

    prepared = await service.prepare_download(_request(), _login_user())

    assert storage.requested_object_names == [first.object_name, repaired.object_name]
    assert ensurer.calls[0]["invalid_generation"] is None
    assert ensurer.calls[1]["invalid_generation"] == 1
    await prepared.close()


@pytest.mark.asyncio
async def test_repaired_artifact_still_invalid_fails_without_unwatermarked_fallback(tmp_path: Path) -> None:
    ensurer = FakeArtifactEnsurer([_artifact(generation=1), _artifact(generation=2)])
    storage = FakeStorage(payloads=[b"broken-one", b"broken-two"])
    service, _ = _build_service(tmp_path, artifact_ensurer=ensurer, storage=storage)

    with pytest.raises(PortalPdfDownloadGenerationError):
        await service.prepare_download(_request(), _login_user())

    assert len(ensurer.calls) == 2
    assert ensurer.calls[1]["invalid_generation"] == 1
    assert storage.requested_object_names == [
        "knowledge/pdf-artifacts/1580/1/current.pdf",
        "knowledge/pdf-artifacts/1580/1/current.pdf",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (PdfArtifactOnDemandTimeoutError(), PortalPdfDownloadTimeoutError),
        (PdfArtifactOnDemandGenerationError(), PortalPdfDownloadGenerationError),
    ],
)
async def test_on_demand_failure_maps_to_safe_download_error(tmp_path: Path, error, expected) -> None:
    ensurer = FakeArtifactEnsurer([error])
    service, fakes = _build_service(tmp_path, artifact_ensurer=ensurer)

    with pytest.raises(expected):
        await service.prepare_download(_request(), _login_user())

    assert fakes["storage"].requested_object_names == []
    assert fakes["lock"].release_calls == [(5, 7, "owner-token")]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("user", "expected_identity"),
    [
        (_user(), "设备管理部-张三--SG001-2026-07-21"),
        (_user(primary_department_name=""), "张三--SG001-2026-07-21"),
        (_user(user_name="", external_id="", primary_department_name=None), "client-name-must-not-be-used-2026-07-21"),
    ],
)
async def test_watermark_identity_comes_from_server_user_record(
    tmp_path: Path,
    user,
    expected_identity: str,
) -> None:
    runner = CapturingRunner()
    service, _ = _build_service(tmp_path, user=user, runner=runner)

    prepared = await service.prepare_download(_request(), _login_user())

    lines = runner.calls[0]["spec"].lines
    assert lines == (
        expected_identity,
        "首钢股份内部资料，严禁外传，违者必究",
    )
    await prepared.close()


@pytest.mark.asyncio
async def test_success_stream_records_once_then_cleans_temp_and_releases_lock(tmp_path: Path) -> None:
    telemetry: list = []
    service, fakes = _build_service(tmp_path, telemetry=telemetry)
    prepared = await service.prepare_download(_request(entry_point="search"), _login_user())
    temp_dir = prepared.path.parent

    chunks = [chunk async for chunk in prepared.iter_bytes(chunk_size=64)]

    assert b"".join(chunks).startswith(b"%PDF")
    assert len(telemetry) == 1
    assert telemetry[0]["entry_point"] == "search"
    assert not temp_dir.exists()
    assert fakes["lock"].release_calls == [(5, 7, "owner-token")]


@pytest.mark.asyncio
async def test_disconnect_after_first_chunk_cleans_without_success_event(tmp_path: Path) -> None:
    telemetry: list = []
    service, fakes = _build_service(tmp_path, telemetry=telemetry)
    prepared = await service.prepare_download(_request(), _login_user())
    temp_dir = prepared.path.parent
    iterator = prepared.iter_bytes(chunk_size=64)

    first_chunk = await iterator.__anext__()
    assert first_chunk
    await iterator.aclose()

    assert telemetry == []
    assert not temp_dir.exists()
    assert fakes["lock"].release_calls == [(5, 7, "owner-token")]


@pytest.mark.asyncio
async def test_generation_task_cancellation_cleans_temp_dir_and_user_lock(tmp_path: Path) -> None:
    service, fakes = _build_service(tmp_path)

    async def cancel_generation(*_args, **_kwargs):
        raise asyncio.CancelledError()

    service._run_with_deadline = cancel_generation

    with pytest.raises(asyncio.CancelledError):
        await service.prepare_download(_request(), _login_user())

    assert list(tmp_path.iterdir()) == []
    assert fakes["lock"].release_calls == [(5, 7, "owner-token")]
    assert fakes["capacity"].active == 0


@pytest.mark.asyncio
async def test_timeout_and_generation_error_cleanup_and_release_resources(tmp_path: Path) -> None:
    for error, expected_error in [
        (PdfWatermarkWorkerTimeout("slow"), PortalPdfDownloadTimeoutError),
        (RuntimeError("sensitive worker detail"), PortalPdfDownloadGenerationError),
    ]:
        request_root = tmp_path / expected_error.__name__
        request_root.mkdir()
        lock = FakeUserLock()
        capacity = PortalPdfDownloadProcessCapacity(2)
        service, _ = _build_service(
            request_root,
            user_lock=lock,
            capacity=capacity,
            runner=CapturingRunner(error=error),
        )

        with pytest.raises(expected_error) as exc_info:
            await service.prepare_download(_request(), _login_user())

        assert "sensitive worker detail" not in str(exc_info.value)
        assert list(request_root.iterdir()) == []
        assert lock.release_calls == [(5, 7, "owner-token")]
        assert capacity.active == 0


@pytest.mark.asyncio
async def test_user_lock_or_process_capacity_busy_returns_429_before_temp_creation(tmp_path: Path) -> None:
    locked_service, _ = _build_service(tmp_path / "locked", user_lock=FakeUserLock(token=None))
    with pytest.raises(PortalPdfDownloadBusyError):
        await locked_service.prepare_download(_request(), _login_user())

    full_capacity = PortalPdfDownloadProcessCapacity(1)
    assert full_capacity.try_acquire() is True
    lock = FakeUserLock()
    full_service, _ = _build_service(tmp_path / "full", user_lock=lock, capacity=full_capacity)
    with pytest.raises(PortalPdfDownloadBusyError):
        await full_service.prepare_download(_request(), _login_user())

    assert lock.release_calls == [(5, 7, "owner-token")]
    assert not (tmp_path / "locked").exists()
    assert not (tmp_path / "full").exists()
    full_capacity.release()


@pytest.mark.asyncio
async def test_redis_user_lock_uses_ttl_and_atomic_ownership_release() -> None:
    class FakeRedis:
        def __init__(self) -> None:
            self.set_calls: list[tuple] = []
            self.eval_calls: list[tuple] = []

        async def set(self, key, value, **kwargs):
            self.set_calls.append((key, value, kwargs))
            return True

        async def eval(self, script, number_of_keys, key, token):
            self.eval_calls.append((script, number_of_keys, key, token))
            return 1

    redis = FakeRedis()
    lock = PortalPdfDownloadUserLock(redis)

    token = await lock.acquire(tenant_id=5, user_id=7, ttl_seconds=90)
    await lock.release(tenant_id=5, user_id=7, token=token)

    key, stored_token, options = redis.set_calls[0]
    assert key == "bisheng:portal_pdf_download:user:5:7"
    assert stored_token == token
    assert options == {"nx": True, "ex": 90}
    script, number_of_keys, released_key, released_token = redis.eval_calls[0]
    assert "redis.call('GET', KEYS[1]) == ARGV[1]" in script
    assert number_of_keys == 1
    assert released_key == key
    assert released_token == token


@pytest.mark.asyncio
async def test_redis_user_lock_failure_is_fail_closed_service_unavailable() -> None:
    class BrokenRedis:
        async def set(self, *_args, **_kwargs):
            raise ConnectionError("redis unavailable")

    lock = PortalPdfDownloadUserLock(BrokenRedis())

    with pytest.raises(PortalPdfDownloadServiceUnavailableError):
        await lock.acquire(tenant_id=5, user_id=7, ttl_seconds=90)
