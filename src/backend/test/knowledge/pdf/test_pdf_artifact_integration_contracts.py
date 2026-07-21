from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.rag.pipeline.transformer import extra_file

_BACKEND = Path(__file__).resolve().parents[3]


def _function_source(relative_path: str, function_name: str) -> str:
    path = _BACKEND / relative_path
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name
    ]
    assert matches, (relative_path, function_name)
    return ast.get_source_segment(source, max(matches, key=lambda node: node.lineno)) or ""


class _Storage:
    def __init__(self) -> None:
        self.uploads = []

    def put_object_sync(self, **kwargs) -> None:
        self.uploads.append(kwargs)


def test_parse_preview_records_current_source_md5(tmp_path, monkeypatch) -> None:
    pdf_path = tmp_path / "preview.pdf"
    pdf_path.write_bytes(b"pdf")
    file = KnowledgeFile(
        id=101,
        tenant_id=7,
        knowledge_id=9,
        file_name="report.docx",
        md5="source-md5",
    )
    transformer = extra_file.ExtraFileTransformer(
        loader=SimpleNamespace(pdf_preview_file_path=str(pdf_path)),
        document_id="101",
        knowledge_id=9,
        knowledge_file=file,
    )
    monkeypatch.setattr(
        extra_file.KnowledgeUtils,
        "get_knowledge_pdf_preview_file_object_name",
        lambda file_id: f"preview/{file_id}.pdf",
        raising=False,
    )
    storage = _Storage()

    transformer._upload_pdf_preview(storage)

    assert file.user_metadata["pdf_preview_object_name"] == "preview/101.pdf"
    assert file.user_metadata["pdf_preview_source_md5"] == "source-md5"


def test_new_upload_and_duplicate_overwrite_md5_contracts_are_present() -> None:
    source = _function_source(
        "bisheng/knowledge/domain/services/knowledge_service.py",
        "process_one_file",
    )
    assert "db_file.md5 = md5_" in source
    assert "request_pdf_artifact_generation_sync(db_file)" in source


def test_sync_and_celery_parse_completion_hooks_enqueue_existing_generation() -> None:
    sync_source = _function_source(
        "bisheng/knowledge/domain/services/knowledge_service.py",
        "sync_process_knowledge_file",
    )
    parse_source = _function_source(
        "bisheng/worker/knowledge/file_worker.py",
        "parse_knowledge_file_celery",
    )
    retry_source = _function_source(
        "bisheng/worker/knowledge/file_worker.py",
        "retry_knowledge_file_celery",
    )
    assert "enqueue_current_pdf_artifact_sync" in sync_source
    assert "enqueue_current_pdf_artifact_sync" in parse_source
    assert "enqueue_current_pdf_artifact_sync" in retry_source


def test_fixed_path_retry_invalidates_before_copy_and_persists_new_md5() -> None:
    source = _function_source(
        "bisheng/knowledge/domain/services/knowledge_utils.py",
        "process_retry_files",
    )
    request_index = source.index("await request_pdf_artifact_generation(")
    copy_index = source.index("copy_object")
    assert request_index < copy_index
    assert 'incoming_md5 = input_file.get("md5")' in source
    assert "file.md5 = effective_md5" in source


def test_web_overwrite_invalidates_before_writing_new_source_bytes() -> None:
    source = _function_source(
        "bisheng/knowledge/domain/services/knowledge_space_service.py",
        "_overwrite_web_link_file",
    )
    request_index = source.index("request_pdf_artifact_generation")
    put_index = source.index("put_object_sync")
    assert request_index < put_index


def test_copy_and_no_parse_upload_directly_enqueue_pdf_generation() -> None:
    copy_source = _function_source(
        "bisheng/worker/knowledge/file_worker.py",
        "copy_normal",
    )
    add_source = _function_source(
        "bisheng/knowledge/domain/services/knowledge_space_service.py",
        "add_file",
    )
    assert "request_pdf_artifact_generation_sync" in copy_source
    assert "enqueue=True" in copy_source
    assert "if not enqueue_processing" in add_source
    assert "enqueue_current_pdf_artifact" in add_source


def test_batch_retry_invalidates_before_dispatch() -> None:
    source = _function_source(
        "bisheng/knowledge/domain/services/knowledge_space_service.py",
        "batch_retry_failed_files",
    )
    request_index = source.index("await request_pdf_artifact_generation(")
    dispatch_index = source.index("retry_knowledge_file_celery.delay")
    status_index = source.index("aupdate_file_status")
    assert status_index < request_index < dispatch_index


def test_minio_cleanup_includes_preview_pdf_and_generated_snapshot() -> None:
    file_source = _function_source(
        "bisheng/api/services/knowledge_imp.py",
        "_knowledge_file_owned_object_names",
    )
    batch_source = _function_source(
        "bisheng/api/services/knowledge_imp.py",
        "delete_minio_file_snapshot_objects",
    )
    compatibility_source = _function_source(
        "bisheng/api/services/knowledge_imp.py",
        "delete_minio_files",
    )
    assert "pdf_preview_object_name" in file_source
    assert "_artifact_owned_object_name" in batch_source
    assert "delete_minio_file_snapshot_objects" in compatibility_source


def test_delete_flows_snapshot_artifacts_before_parent_rows() -> None:
    service_source = _function_source(
        "bisheng/knowledge/domain/services/knowledge_service.py",
        "delete_knowledge_file",
    )
    space_source = _function_source(
        "bisheng/knowledge/domain/services/knowledge_space_service.py",
        "delete_file",
    )
    version_source = _function_source(
        "bisheng/knowledge/domain/services/knowledge_version_service.py",
        "delete_version",
    )
    assert service_source.index("get_pdf_artifact_deletion_snapshots_sync") < service_source.index(
        "KnowledgeFileDao.delete_batch"
    )
    assert "knowledge_file_snapshots" in service_source
    assert space_source.index("get_pdf_artifact_deletion_snapshots") < space_source.index(
        "KnowledgeFileDao.adelete_batch"
    )
    assert "knowledge_file_snapshots" in space_source
    assert version_source.index("get_pdf_artifact_deletion_snapshots") < version_source.index(
        "knowledge_file_repo.delete"
    )

    delayed_task_source = _function_source(
        "bisheng/worker/knowledge/file_worker.py",
        "delete_knowledge_file_celery",
    )
    assert "knowledge_file_snapshots" in delayed_task_source
    assert "delete_minio_file_snapshot_objects" in delayed_task_source
