from types import SimpleNamespace
from unittest.mock import MagicMock

from bisheng.api.v1.schemas import KnowledgeFileOne
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService


def test_new_uploaded_file_initializes_original_origin(tmp_path, monkeypatch):
    upload_path = tmp_path / "document.pdf"
    upload_path.write_bytes(b"document")
    stored_files = []
    storage = SimpleNamespace(
        bucket="knowledge",
        put_object_sync=MagicMock(),
    )

    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_service.file_download",
        lambda _path: (str(upload_path), "document.pdf"),
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_service.get_minio_storage_sync",
        lambda: storage,
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_service.KnowledgeFileDao.get_file_by_condition",
        lambda **_kwargs: [],
    )

    def add_file(file):
        file.id = 100
        stored_files.append(file)
        return file

    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_service.KnowledgeFileDao.add_file",
        add_file,
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_service.KnowledgeFileDao.update",
        lambda file: file,
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_service.KnowledgeUtils.get_knowledge_file_object_name",
        lambda file_id, file_name: f"knowledge/{file_id}/{file_name}",
    )
    monkeypatch.setattr(KnowledgeService, "remove_unused_file", MagicMock())
    monkeypatch.setattr(
        KnowledgeService.audit_telemetry_service,
        "telemetry_new_knowledge_file",
        MagicMock(),
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_pdf_artifact_service.request_pdf_artifact_generation_sync",
        MagicMock(),
    )

    result = KnowledgeService.process_one_file(
        login_user=SimpleNamespace(user_id=501, user_name="上传人"),
        knowledge=Knowledge(id=10, tenant_id=7, name="个人知识库", type=3),
        file_info=KnowledgeFileOne(file_path="upload-token"),
        split_rule={},
    )

    assert stored_files == [result]
    assert result.original_uploader_id == 501
    assert result.original_knowledge_id == 10
