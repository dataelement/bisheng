from unittest.mock import MagicMock, patch

import pytest  # noqa: F401

from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileStatus
from bisheng.worker.knowledge.file_title_worker import (
    extract_knowledge_file_title_celery,
)


class TestExtractKnowledgeFileTitleCelery:
    @patch("bisheng.worker.knowledge.file_title_worker.KnowledgeFileDao.query_by_id_sync")
    @patch("bisheng.worker.knowledge.file_title_worker.download_minio_file")
    @patch("bisheng.worker.knowledge.file_title_worker.FileTitleExtractorService.extract_title")
    @patch("bisheng.worker.knowledge.file_title_worker.FileAliasNameGeneratorService.generate_alias_name")
    @patch("bisheng.worker.knowledge.file_title_worker.KnowledgeFileDao.update")
    @patch("bisheng.worker.knowledge.file_title_worker.parse_knowledge_file_celery")
    def test_alias_generated_and_persisted(
        self,
        mock_parse_task,
        mock_update,
        mock_generate_alias,
        mock_extract,
        mock_download,
        mock_query,
        tmp_path,
    ):
        db_file = MagicMock()
        db_file.id = 1
        db_file.knowledge_id = 1
        db_file.status = KnowledgeFileStatus.WAITING.value
        db_file.file_name = "old_name.pdf"
        db_file.alias_name = None
        db_file.object_name = "original/1.pdf"
        db_file.user_id = 10
        db_file.tenant_id = 1
        mock_query.return_value = db_file

        tmp_file = tmp_path / "1.pdf"
        tmp_file.write_text("dummy")
        mock_download.return_value = (str(tmp_file), "")
        mock_extract.return_value = "Extracted Title"
        mock_generate_alias.return_value = "AI Generated Alias.pdf"

        extract_knowledge_file_title_celery(1, "preview-key")

        assert db_file.file_name == "old_name.pdf"
        assert db_file.alias_name == "AI Generated Alias.pdf"
        mock_update.assert_called_once_with(db_file)
        mock_parse_task.delay.assert_called_once_with(1, "preview-key", None)

    @patch("bisheng.worker.knowledge.file_title_worker.KnowledgeFileDao.query_by_id_sync")
    @patch("bisheng.worker.knowledge.file_title_worker.download_minio_file")
    @patch("bisheng.worker.knowledge.file_title_worker.FileTitleExtractorService.extract_title")
    @patch("bisheng.worker.knowledge.file_title_worker.FileAliasNameGeneratorService.generate_alias_name")
    @patch("bisheng.worker.knowledge.file_title_worker.KnowledgeFileDao.update")
    @patch("bisheng.worker.knowledge.file_title_worker.parse_knowledge_file_celery")
    def test_no_title_keeps_alias_empty(
        self,
        mock_parse_task,
        mock_update,
        mock_generate_alias,
        mock_extract,
        mock_download,
        mock_query,
        tmp_path,
    ):
        db_file = MagicMock()
        db_file.id = 2
        db_file.knowledge_id = 1
        db_file.status = KnowledgeFileStatus.WAITING.value
        db_file.file_name = "old_name.txt"
        db_file.alias_name = None
        db_file.object_name = "original/2.txt"
        db_file.user_id = 10
        db_file.tenant_id = 1
        mock_query.return_value = db_file

        tmp_file = tmp_path / "2.txt"
        tmp_file.write_text("dummy")
        mock_download.return_value = (str(tmp_file), "")
        mock_extract.return_value = None

        extract_knowledge_file_title_celery(2, "preview-key")

        assert db_file.file_name == "old_name.txt"
        assert db_file.alias_name is None
        mock_generate_alias.assert_not_called()
        mock_update.assert_not_called()
        mock_parse_task.delay.assert_called_once_with(2, "preview-key", None)

    @patch("bisheng.worker.knowledge.file_title_worker.KnowledgeFileDao.query_by_id_sync")
    @patch("bisheng.worker.knowledge.file_title_worker.parse_knowledge_file_celery")
    def test_file_not_found_still_triggers_parse(self, mock_parse_task, mock_query):
        mock_query.return_value = None

        extract_knowledge_file_title_celery(3, "preview-key")

        mock_parse_task.delay.assert_called_once_with(3, "preview-key", None)

    @patch("bisheng.worker.knowledge.file_title_worker.KnowledgeFileDao.query_by_id_sync")
    @patch("bisheng.worker.knowledge.file_title_worker.download_minio_file")
    @patch("bisheng.worker.knowledge.file_title_worker.parse_knowledge_file_celery")
    def test_download_failure_still_triggers_parse(self, mock_parse_task, mock_download, mock_query):
        db_file = MagicMock()
        db_file.id = 4
        db_file.knowledge_id = 1
        db_file.status = KnowledgeFileStatus.WAITING.value
        db_file.file_name = "old_name.pdf"
        db_file.object_name = "original/4.pdf"
        mock_query.return_value = db_file
        mock_download.side_effect = RuntimeError("download error")

        extract_knowledge_file_title_celery(4, "preview-key")

        mock_parse_task.delay.assert_called_once_with(4, "preview-key", None)
