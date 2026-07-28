"""Unit tests for knowledge recycle-bin helpers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.common.errcode.knowledge import KnowledgeRecycleForbiddenError
from bisheng.knowledge.domain.models.knowledge_file import FileType
from bisheng.knowledge.domain.services.knowledge_recycle_service import (
    DEFAULT_RETENTION_DAYS,
    KnowledgeRecycleService,
)
from bisheng.knowledge.rag.version_filter import build_primary_only_filter


def test_path_fingerprint_stable():
    a = KnowledgeRecycleService._path_fingerprint("/1/2/3")
    b = KnowledgeRecycleService._path_fingerprint("/1/2/3")
    c = KnowledgeRecycleService._path_fingerprint("/1/2/4")
    assert a == b
    assert a != c
    assert len(a) == 32


def test_coerce_file_type_preserves_dir_zero():
    # DIR=0 must not be treated as falsy and replaced with FILE.
    assert KnowledgeRecycleService._coerce_file_type(FileType.DIR) == FileType.DIR.value
    assert KnowledgeRecycleService._coerce_file_type(0) == FileType.DIR.value
    assert KnowledgeRecycleService._coerce_file_type(FileType.FILE) == FileType.FILE.value
    assert KnowledgeRecycleService._coerce_file_type(1) == FileType.FILE.value
    assert KnowledgeRecycleService._coerce_file_type(None) == FileType.FILE.value


def test_find_file_conflicts_scopes_to_knowledge_space():
    import inspect

    src = inspect.getsource(KnowledgeRecycleService._find_file_conflicts)
    assert "KnowledgeFile.knowledge_id == knowledge_id" in src
    assert "file_level_path" not in src
    assert "FileType.FILE" in src


def test_conflict_parent_display_path():
    rec = SimpleNamespace(file_level_path="/10/20")
    assert KnowledgeRecycleService._conflict_parent_display_path(rec, {10: "a", 20: "b"}) == "/a/b"
    assert KnowledgeRecycleService._conflict_parent_display_path(SimpleNamespace(file_level_path=""), {}) == "/"
    assert (
        KnowledgeRecycleService._conflict_parent_display_path(SimpleNamespace(file_level_path="/819"), {819: "a"})
        == "/a"
    )


def test_build_primary_only_filter_merges_recycled_ids():
    milvus, es = build_primary_only_filter([10, 3, 10])
    assert milvus == "document_id not in [3, 10]"
    assert es
    assert es[0]["bool"]["must_not"]["terms"]["metadata.document_id"] == [3, 10]


@pytest.mark.asyncio
async def test_require_admin_blocks_normal_user():
    user = SimpleNamespace(
        user_id=2,
        user_name="u",
        tenant_id=1,
        is_admin=lambda: False,
        is_global_super=False,
    )
    svc = KnowledgeRecycleService(user)  # type: ignore[arg-type]
    with pytest.raises(KnowledgeRecycleForbiddenError):
        svc._require_admin()


@pytest.mark.asyncio
async def test_get_retention_days_default():
    with patch(
        "bisheng.knowledge.domain.services.knowledge_recycle_service.ConfigDao.aget_config_by_key",
        new=AsyncMock(return_value=None),
    ):
        days = await KnowledgeRecycleService.get_retention_days()
    assert days == DEFAULT_RETENTION_DAYS


def test_build_minio_deletion_snapshots_includes_object_keys():
    files = [
        SimpleNamespace(
            id=99,
            file_name="doc.pdf",
            object_name="original/99.pdf",
            preview_file_object_name="preview/99.pdf",
            bbox_object_name="partitions/99.json",
            thumbnails=None,
            user_metadata={"pdf_preview_object_name": "preview/99-pdf.pdf"},
        )
    ]
    snaps = KnowledgeRecycleService._build_minio_deletion_snapshots(files)
    assert snaps == [
        {
            "id": 99,
            "file_name": "doc.pdf",
            "object_name": "original/99.pdf",
            "preview_file_object_name": "preview/99.pdf",
            "bbox_object_name": "partitions/99.json",
            "thumbnails": None,
            "user_metadata": {"pdf_preview_object_name": "preview/99-pdf.pdf"},
        }
    ]


@pytest.mark.asyncio
async def test_overwrite_conflicts_clears_minio_with_snapshots():
    user = SimpleNamespace(user_id=1, user_name="admin", tenant_id=1, is_admin=lambda: True)
    svc = KnowledgeRecycleService(user)  # type: ignore[arg-type]
    item = SimpleNamespace(file_id=10, display_name="doc.pdf", md5="abc")
    conflict_file = SimpleNamespace(
        id=20,
        file_name="doc.pdf",
        object_name="original/20.pdf",
        preview_file_object_name=None,
        bbox_object_name=None,
        thumbnails=None,
        user_metadata={},
    )
    knowledge = SimpleNamespace(id=19)

    with (
        patch.object(
            svc,
            "_find_file_conflicts",
            new=AsyncMock(return_value=[{"target_file_id": 20, "name": "doc.pdf", "reason": "md5"}]),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_recycle_service.KnowledgeFileDao.aget_file_by_ids",
            new=AsyncMock(return_value=[conflict_file]),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_recycle_service.KnowledgeDao.aquery_by_id",
            new=AsyncMock(return_value=knowledge),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_pdf_artifact_service.get_pdf_artifact_deletion_snapshots",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "bisheng.api.services.knowledge_imp.delete_vector_files",
        ) as delete_vectors,
        patch(
            "bisheng.api.services.knowledge_imp.delete_minio_file_snapshot_objects",
        ) as delete_minio,
        patch(
            "bisheng.knowledge.domain.services.knowledge_recycle_service.get_async_db_session",
        ) as db_session,
    ):
        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.execute = AsyncMock()
        session.commit = AsyncMock()
        db_session.return_value = session

        await svc._overwrite_conflicts(item, target_kid=19)  # type: ignore[arg-type]

    delete_vectors.assert_called_once_with([20], knowledge)
    delete_minio.assert_called_once()
    snaps, pdf_snaps = delete_minio.call_args.args
    assert snaps[0]["object_name"] == "original/20.pdf"
    assert pdf_snaps == []
    session.execute.assert_awaited()
    session.commit.assert_awaited()
