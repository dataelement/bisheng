from __future__ import annotations

from bisheng.api.services import knowledge_imp
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_file_pdf_artifact import (
    KnowledgeFilePdfArtifactOrigin,
)
from bisheng.knowledge.domain.services.knowledge_pdf_artifact_service import (
    PdfArtifactDeletionSnapshot,
)


class _Storage:
    bucket = "default"

    def __init__(self, failing_object: str | None = None) -> None:
        self.failing_object = failing_object
        self.removed = []

    def remove_object_sync(self, *, bucket_name, object_name) -> None:
        self.removed.append((bucket_name, object_name))
        if object_name == self.failing_object:
            raise FileNotFoundError(object_name)


def _snapshot(file_id: int, origin, object_name: str):
    return PdfArtifactDeletionSnapshot(
        tenant_id=7,
        knowledge_file_id=file_id,
        generation=2,
        object_name=object_name,
        artifact_origin=origin.value,
    )


def test_file_cleanup_deduplicates_existing_owners_and_adds_generated_object(
    monkeypatch,
) -> None:
    storage = _Storage()
    monkeypatch.setattr(knowledge_imp, "get_minio_storage_sync", lambda: storage)
    monkeypatch.setattr(
        knowledge_imp.KnowledgeUtils,
        "resolve_preview_object_name",
        lambda *args: "preview/101.pdf",
        raising=False,
    )
    file = KnowledgeFile(
        id=101,
        tenant_id=7,
        knowledge_id=9,
        file_name="report.docx",
        object_name="original/101.docx",
        bbox_object_name="partitions/101.json",
        preview_file_object_name="preview/101.pdf",
        user_metadata={"pdf_preview_object_name": "preview/101.pdf"},
    )
    snapshots = [
        _snapshot(101, KnowledgeFilePdfArtifactOrigin.GENERATED, "knowledge/pdf-artifacts/101/2/a.pdf"),
        _snapshot(101, KnowledgeFilePdfArtifactOrigin.ORIGINAL, "must-not-delete-as-artifact.pdf"),
    ]

    assert knowledge_imp.delete_minio_files(file, snapshots) is True

    removed = [object_name for _, object_name in storage.removed]
    assert set(removed) == {
        "101",
        "original/101.docx",
        "partitions/101.json",
        "preview/101.pdf",
        "knowledge/pdf-artifacts/101/2/a.pdf",
    }
    assert len(removed) == len(set(removed))
    assert "must-not-delete-as-artifact.pdf" not in removed


def test_snapshot_cleanup_is_idempotent_and_continues_after_not_found(monkeypatch) -> None:
    storage = _Storage(failing_object="knowledge/pdf-artifacts/101/2/missing.pdf")
    monkeypatch.setattr(knowledge_imp, "get_minio_storage_sync", lambda: storage)
    snapshots = [
        _snapshot(
            101,
            KnowledgeFilePdfArtifactOrigin.GENERATED,
            "knowledge/pdf-artifacts/101/2/missing.pdf",
        ).to_dict(),
        _snapshot(
            102,
            KnowledgeFilePdfArtifactOrigin.GENERATED,
            "knowledge/pdf-artifacts/102/1/live.pdf",
        ).to_dict(),
        _snapshot(103, KnowledgeFilePdfArtifactOrigin.PARSE_PREVIEW, "preview/103.pdf").to_dict(),
    ]

    knowledge_imp.delete_pdf_artifact_snapshot_objects(snapshots)

    removed = {object_name for _, object_name in storage.removed}
    assert removed == {
        "knowledge/pdf-artifacts/101/2/missing.pdf",
        "knowledge/pdf-artifacts/102/1/live.pdf",
    }


def test_delayed_cleanup_uses_file_snapshot_after_parent_row_is_gone(monkeypatch) -> None:
    storage = _Storage()
    monkeypatch.setattr(knowledge_imp, "get_minio_storage_sync", lambda: storage)
    monkeypatch.setattr(
        knowledge_imp.KnowledgeUtils,
        "resolve_preview_object_name",
        lambda *args: "preview/201.pdf",
        raising=False,
    )
    file_snapshot = {
        "id": 201,
        "file_name": "manual.docx",
        "object_name": "original/201.docx",
        "preview_file_object_name": "preview/201.pdf",
        "bbox_object_name": "bbox/201.json",
        "thumbnails": "thumbnail/201.png",
        "user_metadata": {"pdf_preview_object_name": "preview/201.pdf"},
    }
    artifact_snapshot = _snapshot(
        201,
        KnowledgeFilePdfArtifactOrigin.GENERATED,
        "knowledge/pdf-artifacts/201/3/result.pdf",
    ).to_dict()

    knowledge_imp.delete_minio_file_snapshot_objects(
        [file_snapshot],
        [artifact_snapshot],
    )

    removed = [object_name for _, object_name in storage.removed]
    assert set(removed) == {
        "201",
        "original/201.docx",
        "preview/201.pdf",
        "bbox/201.json",
        "thumbnail/201.png",
        "knowledge/pdf-artifacts/201/3/result.pdf",
    }
    assert len(removed) == len(set(removed))
