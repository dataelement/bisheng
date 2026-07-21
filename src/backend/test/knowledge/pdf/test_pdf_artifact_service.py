from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from types import SimpleNamespace

import pytest
from kombu.exceptions import OperationalError
from loguru import logger

from bisheng.core.config.settings import KnowledgePdfArtifactConf
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_file_pdf_artifact import (
    KnowledgeFilePdfArtifact,
    KnowledgeFilePdfArtifactOrigin,
    KnowledgeFilePdfArtifactStatus,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_file_pdf_artifact_repository import (
    PdfArtifactGenerationRequest,
)
from bisheng.knowledge.domain.services import knowledge_pdf_artifact_service as service_module
from bisheng.knowledge.domain.services.knowledge_pdf_artifact_service import (
    KnowledgePdfArtifactService,
)


class _SyncRepository:
    def __init__(self) -> None:
        self.snapshots = []
        self.current = None
        self.failed = []
        self.rows = []

    def request_generation(self, snapshot):
        self.snapshots.append(snapshot)
        artifact = KnowledgeFilePdfArtifact(
            id=11,
            tenant_id=snapshot.tenant_id,
            knowledge_file_id=snapshot.knowledge_file_id,
            source_object_name=snapshot.source_object_name,
            source_md5=snapshot.source_md5,
            generation=3,
            status=KnowledgeFilePdfArtifactStatus.WAITING.value,
        )
        self.current = artifact
        return PdfArtifactGenerationRequest(artifact, None, None)

    def find_current(self, tenant_id, knowledge_file_id):
        return self.current

    def find_available(self, tenant_id, knowledge_file_id):
        return self.current

    def fail_generation(self, tenant_id, knowledge_file_id, generation, last_error):
        self.failed.append((tenant_id, knowledge_file_id, generation, last_error))
        return True

    def find_by_file_ids(self, tenant_id, knowledge_file_ids):
        return self.rows


class _AsyncRepository(_SyncRepository):
    async def request_generation(self, snapshot):
        return super().request_generation(snapshot)

    async def find_current(self, tenant_id, knowledge_file_id):
        return super().find_current(tenant_id, knowledge_file_id)

    async def find_available(self, tenant_id, knowledge_file_id):
        return super().find_available(tenant_id, knowledge_file_id)

    async def fail_generation(self, tenant_id, knowledge_file_id, generation, last_error):
        return super().fail_generation(tenant_id, knowledge_file_id, generation, last_error)

    async def find_by_file_ids(self, tenant_id, knowledge_file_ids):
        return super().find_by_file_ids(tenant_id, knowledge_file_ids)


class _Task:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls = []

    def apply_async(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error


def _file(**updates) -> KnowledgeFile:
    values = {
        "id": 101,
        "tenant_id": 7,
        "knowledge_id": 9,
        "file_name": "report.docx",
        "file_type": FileType.FILE.value,
        "file_source": "upload",
        "object_name": "original/101.docx",
        "md5": "old-md5",
    }
    values.update(updates)
    return KnowledgeFile(**values)


def _service(repository, task=None) -> KnowledgePdfArtifactService:
    return KnowledgePdfArtifactService(
        repository=repository,
        config=KnowledgePdfArtifactConf(),
        task=task or _Task(),
    )


@pytest.mark.parametrize(
    "file",
    [
        _file(file_type=FileType.DIR.value),
        _file(file_source="favorite_reference", object_name=None),
        _file(object_name=None),
        _file(file_name="archive.zip", object_name="original/101.zip"),
        _file(id=None),
    ],
)
def test_request_generation_skips_non_physical_or_unsupported_records(file) -> None:
    repository = _SyncRepository()

    assert _service(repository).request_generation_sync(file) is None
    assert repository.snapshots == []


def test_request_generation_uses_new_md5_before_fixed_path_overwrite() -> None:
    repository = _SyncRepository()
    result = _service(repository).request_generation_sync(
        _file(),
        source_object_name="original/101.docx",
        source_md5="new-md5",
    )

    assert result is not None
    assert repository.snapshots[0].source_object_name == "original/101.docx"
    assert repository.snapshots[0].source_md5 == "new-md5"


def test_available_reference_requires_current_source_snapshot_and_hides_origin() -> None:
    repository = _SyncRepository()
    service = _service(repository)
    request = service.request_generation_sync(_file())
    assert request is not None
    artifact = request.artifact
    artifact.status = KnowledgeFilePdfArtifactStatus.SUCCESS.value
    artifact.artifact_origin = KnowledgeFilePdfArtifactOrigin.GENERATED.value
    artifact.object_name = "knowledge/pdf-artifacts/101/3/a.pdf"
    artifact.artifact_sha256 = "a" * 64
    artifact.page_count = 2
    artifact.artifact_size = 128
    artifact.completed_at = datetime(2026, 7, 20)

    reference = service.get_available_reference_sync(_file())

    assert reference is not None
    assert reference.object_name == "knowledge/pdf-artifacts/101/3/a.pdf"
    assert "artifact_origin" not in asdict(reference)
    assert service.get_available_reference_sync(_file(md5="changed")) is None
    assert service.get_available_reference_sync(_file(object_name="original/changed.docx")) is None


def test_enqueue_current_uses_dedicated_queue_and_explicit_tenant_header() -> None:
    repository = _SyncRepository()
    task = _Task()
    service = _service(repository, task)
    request = service.request_generation_sync(_file())
    assert request is not None

    assert service.enqueue_current_sync(tenant_id=7, knowledge_file_id=101) is True
    assert task.calls == [
        {
            "args": (101, 3, 7),
            "queue": "knowledge_pdf_celery",
            "headers": {"tenant_id": 7},
        }
    ]


def test_disabled_config_still_invalidates_fixed_path_but_skips_publish() -> None:
    repository = _SyncRepository()
    task = _Task()
    service = KnowledgePdfArtifactService(
        repository=repository,
        config=KnowledgePdfArtifactConf(enabled=False),
        task=task,
    )

    request = service.request_generation_sync(
        _file(),
        source_object_name="original/101.docx",
        source_md5="new-md5",
    )

    assert request is not None
    assert repository.snapshots[0].source_md5 == "new-md5"
    assert service.enqueue_current_sync(tenant_id=7, knowledge_file_id=101) is False
    assert task.calls == []


def test_broker_failure_marks_generation_failed_without_raising() -> None:
    repository = _SyncRepository()
    task = _Task(OperationalError("password=must-not-leak"))
    service = _service(repository, task)
    service.request_generation_sync(_file())

    assert service.enqueue_current_sync(tenant_id=7, knowledge_file_id=101) is False
    assert repository.failed == [(7, 101, 3, "publish:OperationalError")]


def test_completion_hook_logs_only_error_type(monkeypatch: pytest.MonkeyPatch) -> None:
    messages: list[str] = []

    def failing_context():
        raise RuntimeError("password=must-not-leak")

    monkeypatch.setattr(service_module, "get_knowledge_pdf_artifact_service_sync", failing_context)
    sink_id = logger.add(messages.append, format="{message}")
    try:
        assert (
            service_module.enqueue_current_pdf_artifact_sync(
                tenant_id=7,
                knowledge_file_id=101,
            )
            is False
        )
    finally:
        logger.remove(sink_id)

    rendered = "\n".join(messages)
    assert "RuntimeError" in rendered
    assert "must-not-leak" not in rendered


def test_deletion_snapshot_only_exposes_generated_objects_as_artifact_owned() -> None:
    repository = _SyncRepository()
    repository.rows = [
        SimpleNamespace(
            tenant_id=7,
            knowledge_file_id=101,
            generation=1,
            object_name="original/101.pdf",
            artifact_origin=KnowledgeFilePdfArtifactOrigin.ORIGINAL.value,
        ),
        SimpleNamespace(
            tenant_id=7,
            knowledge_file_id=102,
            generation=1,
            object_name="preview/102.pdf",
            artifact_origin=KnowledgeFilePdfArtifactOrigin.PARSE_PREVIEW.value,
        ),
        SimpleNamespace(
            tenant_id=7,
            knowledge_file_id=103,
            generation=2,
            object_name="knowledge/pdf-artifacts/103/2/a.pdf",
            artifact_origin=KnowledgeFilePdfArtifactOrigin.GENERATED.value,
        ),
    ]

    snapshots = _service(repository).build_deletion_snapshots_sync(7, [101, 102, 103])

    assert [snapshot.artifact_owned_object_name for snapshot in snapshots] == [
        None,
        None,
        "knowledge/pdf-artifacts/103/2/a.pdf",
    ]


async def test_async_request_and_enqueue_reuses_the_same_rules() -> None:
    repository = _AsyncRepository()
    task = _Task()
    service = _service(repository, task)

    request = await service.request_generation(_file())
    assert request is not None
    assert await service.enqueue_current(tenant_id=7, knowledge_file_id=101) is True
    assert task.calls[0]["headers"] == {"tenant_id": 7}
