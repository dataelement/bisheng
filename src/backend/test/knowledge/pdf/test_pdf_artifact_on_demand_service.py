from __future__ import annotations

import asyncio
import threading
from datetime import datetime
from types import SimpleNamespace

import pytest

from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_file_pdf_artifact import KnowledgeFilePdfArtifactStatus
from bisheng.knowledge.domain.services.knowledge_pdf_artifact_service import PdfArtifactReference
from bisheng.knowledge.domain.services.pdf_artifact_on_demand_service import (
    PdfArtifactGenerationLock,
    PdfArtifactOnDemandGenerationError,
    PdfArtifactOnDemandService,
    PdfArtifactOnDemandTimeoutError,
)


def _file() -> KnowledgeFile:
    return KnowledgeFile(
        id=101,
        tenant_id=7,
        knowledge_id=9,
        file_name="report.docx",
        file_type=FileType.FILE.value,
        object_name="original/101.docx",
        md5="source-v1",
    )


def _reference(generation: int = 1) -> PdfArtifactReference:
    return PdfArtifactReference(
        tenant_id=7,
        knowledge_file_id=101,
        generation=generation,
        object_name=f"knowledge/pdf-artifacts/101/{generation}/current.pdf",
        artifact_sha256="a" * 64,
        page_count=1,
        artifact_size=100,
        completed_at=datetime(2026, 7, 21),
    )


class FakeArtifactService:
    def __init__(self, state: dict) -> None:
        self.state = state
        self.requests: list[int | None] = []
        self.failures: list[tuple[int, str]] = []

    async def request_on_demand_generation(self, file, *, invalid_generation=None):
        self.requests.append(invalid_generation)
        generation = 1 if invalid_generation is None else invalid_generation + 1
        return SimpleNamespace(
            artifact=SimpleNamespace(
                tenant_id=file.tenant_id,
                knowledge_file_id=file.id,
                generation=generation,
                status=KnowledgeFilePdfArtifactStatus.WAITING.value,
            )
        )

    async def fail_generation(self, *, tenant_id, knowledge_file_id, generation, error):
        assert tenant_id == 7
        assert knowledge_file_id == 101
        self.failures.append((generation, error))


class FakeLock:
    def __init__(self, tokens: list[str | None] | None = None) -> None:
        self.tokens = list(tokens or ["owner-token"])
        self.acquire_calls: list[tuple[int, int, int]] = []
        self.release_calls: list[tuple[int, int, str]] = []

    async def acquire(self, *, tenant_id: int, knowledge_file_id: int, ttl_seconds: int):
        self.acquire_calls.append((tenant_id, knowledge_file_id, ttl_seconds))
        return self.tokens.pop(0) if self.tokens else None

    async def release(self, *, tenant_id: int, knowledge_file_id: int, token: str) -> None:
        self.release_calls.append((tenant_id, knowledge_file_id, token))


def _build_service(
    state: dict,
    *,
    lock: FakeLock | None = None,
    runner=None,
    timeout_seconds: int = 300,
    monotonic=None,
    sleep=None,
):
    artifact_service = FakeArtifactService(state)
    selected_lock = lock or FakeLock()

    async def accessor(_file_record):
        return state.get("reference")

    def successful_runner(*, tenant_id: int, knowledge_file_id: int, generation: int, config):
        assert tenant_id == 7
        assert knowledge_file_id == 101
        state["reference"] = _reference(generation)

    service = PdfArtifactOnDemandService(
        artifact_service=artifact_service,
        artifact_accessor=accessor,
        generation_runner=runner or successful_runner,
        generation_lock=selected_lock,
        config=SimpleNamespace(
            on_demand_timeout_seconds=timeout_seconds,
            generation_lock_ttl_seconds=330,
        ),
        monotonic=monotonic,
        sleep=sleep,
    )
    return service, artifact_service, selected_lock


@pytest.mark.asyncio
async def test_valid_reference_returns_without_generation_or_lock() -> None:
    state = {"reference": _reference()}
    service, artifact_service, lock = _build_service(state)

    result = await service.ensure_available(_file())

    assert result == state["reference"]
    assert artifact_service.requests == []
    assert lock.acquire_calls == []


@pytest.mark.asyncio
async def test_missing_reference_is_generated_and_persisted_in_current_request() -> None:
    state: dict = {"reference": None}
    service, artifact_service, lock = _build_service(state)

    result = await service.ensure_available(_file())

    assert result == _reference(1)
    assert artifact_service.requests == [None]
    assert lock.release_calls == [(7, 101, "owner-token")]


@pytest.mark.asyncio
async def test_non_owner_waits_for_same_file_generation_result() -> None:
    state: dict = {"reference": None}
    lock = FakeLock(tokens=[None])

    async def publish_result(_seconds: float) -> None:
        state["reference"] = _reference(2)

    service, artifact_service, _ = _build_service(state, lock=lock, sleep=publish_result)

    result = await service.ensure_available(_file())

    assert result == _reference(2)
    assert artifact_service.requests == []
    assert lock.release_calls == []


@pytest.mark.asyncio
async def test_broken_success_generation_is_repaired_only_once() -> None:
    state = {"reference": _reference(1)}
    service, artifact_service, lock = _build_service(state)

    result = await service.ensure_available(_file(), invalid_generation=1)

    assert result == _reference(2)
    assert artifact_service.requests == [1]
    assert lock.release_calls == [(7, 101, "owner-token")]


@pytest.mark.asyncio
async def test_generation_failure_is_persisted_and_sanitized() -> None:
    state: dict = {"reference": None}

    def broken_runner(**_kwargs):
        raise RuntimeError("storage secret must not leak")

    service, artifact_service, lock = _build_service(state, runner=broken_runner)

    with pytest.raises(PdfArtifactOnDemandGenerationError) as exc_info:
        await service.ensure_available(_file())

    assert "storage secret" not in str(exc_info.value)
    assert artifact_service.failures == [(1, "process:RuntimeError")]
    assert lock.release_calls == [(7, 101, "owner-token")]


@pytest.mark.asyncio
async def test_generation_without_available_reference_is_marked_failed() -> None:
    state: dict = {"reference": None}

    def no_result_runner(**_kwargs):
        return None

    service, artifact_service, _ = _build_service(state, runner=no_result_runner)

    with pytest.raises(PdfArtifactOnDemandGenerationError):
        await service.ensure_available(_file())

    assert artifact_service.failures == [(1, "process:PdfArtifactOnDemandGenerationError")]


@pytest.mark.asyncio
async def test_waiting_for_generation_obeys_request_deadline() -> None:
    state: dict = {"reference": None}
    clock = {"value": 0.0}

    def monotonic() -> float:
        return clock["value"]

    async def advance(seconds: float) -> None:
        clock["value"] += seconds

    service, _, _ = _build_service(
        state,
        lock=FakeLock(tokens=[None]),
        timeout_seconds=2,
        monotonic=monotonic,
        sleep=advance,
    )

    with pytest.raises(PdfArtifactOnDemandTimeoutError):
        await service.ensure_available(_file())


@pytest.mark.asyncio
async def test_timed_out_runner_keeps_file_lock_until_thread_finishes() -> None:
    state: dict = {"reference": None}
    finished = threading.Event()

    def slow_runner(**_kwargs):
        finished.wait(timeout=1)

    service, artifact_service, lock = _build_service(
        state,
        runner=slow_runner,
        timeout_seconds=0.01,
    )

    with pytest.raises(PdfArtifactOnDemandTimeoutError):
        await service.ensure_available(_file())

    assert artifact_service.failures == [(1, "process:TimeoutError")]
    assert lock.release_calls == []
    finished.set()
    for _ in range(20):
        if lock.release_calls:
            break
        await asyncio.sleep(0.01)
    assert lock.release_calls == [(7, 101, "owner-token")]


@pytest.mark.asyncio
async def test_redis_generation_lock_has_file_scope_ttl_and_owner_release() -> None:
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
    lock = PdfArtifactGenerationLock(redis)

    token = await lock.acquire(tenant_id=7, knowledge_file_id=101, ttl_seconds=330)
    await lock.release(tenant_id=7, knowledge_file_id=101, token=token)

    key, stored_token, options = redis.set_calls[0]
    assert key == "bisheng:knowledge_pdf_artifact:generation:7:101"
    assert stored_token == token
    assert options == {"nx": True, "ex": 330}
    assert "redis.call('GET', KEYS[1]) == ARGV[1]" in redis.eval_calls[0][0]
