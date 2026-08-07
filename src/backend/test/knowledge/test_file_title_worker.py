from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch

from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileStatus


def _load_file_title_worker():
    """Load the target file without the shared Celery package pre-mock."""

    worker_main_name = "bisheng.worker.main"
    lease_name = "bisheng.knowledge.domain.services.knowledge_parse_processing_lease"
    previous_modules = {
        worker_main_name: sys.modules.get(worker_main_name),
        lease_name: sys.modules.get(lease_name),
    }

    class CeleryStub:
        @staticmethod
        def task(**_options):
            return lambda function: function

    worker_main = ModuleType(worker_main_name)
    worker_main.bisheng_celery = CeleryStub()
    lease_module = ModuleType(lease_name)
    lease_module.track_knowledge_parse_delivery = lambda _stage: lambda function: function
    sys.modules[worker_main_name] = worker_main
    sys.modules[lease_name] = lease_module
    try:
        module_path = Path(__file__).resolve().parents[2] / "bisheng/worker/knowledge/file_title_worker.py"
        spec = importlib.util.spec_from_file_location(
            "file_title_worker_under_test",
            module_path,
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for name, previous in previous_modules.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


file_title_worker = _load_file_title_worker()


def _parse_dispatch_kwargs(file_id: int, preview_cache_key: str) -> dict:
    return {
        "stage": file_title_worker.KnowledgeParseStage.PARSE,
        "file_id": file_id,
        "preview_cache_key": preview_cache_key,
        "callback_url": None,
    }


class TestExtractKnowledgeFileTitleCelery:
    @patch("bisheng.knowledge.domain.services.knowledge_parse_dispatch_service.dispatch_knowledge_parse_task_sync")
    def test_alias_generated_and_persisted(self, mock_dispatch, tmp_path):
        db_file = SimpleNamespace(
            id=1,
            knowledge_id=1,
            status=KnowledgeFileStatus.WAITING.value,
            file_name="old_name.pdf",
            alias_name=None,
            object_name="original/1.pdf",
            user_id=10,
            tenant_id=1,
        )
        tmp_file = tmp_path / "1.pdf"
        tmp_file.write_text("dummy")

        with (
            patch.object(
                file_title_worker.KnowledgeFileDao,
                "query_by_id_sync",
                return_value=db_file,
            ),
            patch.object(
                file_title_worker,
                "download_minio_file",
                return_value=(str(tmp_file), ""),
            ),
            patch.object(
                file_title_worker.FileTitleExtractorService,
                "extract_title",
                return_value="Extracted Title",
            ),
            patch.object(
                file_title_worker.FileAliasNameGeneratorService,
                "generate_alias_name",
                return_value="AI Generated Alias.pdf",
            ),
            patch.object(file_title_worker.KnowledgeFileDao, "update") as mock_update,
        ):
            file_title_worker.extract_knowledge_file_title_celery(1, "preview-key")

        assert db_file.file_name == "old_name.pdf"
        assert db_file.alias_name == "AI Generated Alias.pdf"
        mock_update.assert_called_once_with(db_file)
        mock_dispatch.assert_called_once_with(**_parse_dispatch_kwargs(1, "preview-key"))

    @patch("bisheng.knowledge.domain.services.knowledge_parse_dispatch_service.dispatch_knowledge_parse_task_sync")
    def test_no_title_keeps_alias_empty(self, mock_dispatch, tmp_path):
        db_file = SimpleNamespace(
            id=2,
            knowledge_id=1,
            status=KnowledgeFileStatus.WAITING.value,
            file_name="old_name.txt",
            alias_name=None,
            object_name="original/2.txt",
            user_id=10,
            tenant_id=1,
        )
        tmp_file = tmp_path / "2.txt"
        tmp_file.write_text("dummy")

        with (
            patch.object(
                file_title_worker.KnowledgeFileDao,
                "query_by_id_sync",
                return_value=db_file,
            ),
            patch.object(
                file_title_worker,
                "download_minio_file",
                return_value=(str(tmp_file), ""),
            ),
            patch.object(
                file_title_worker.FileTitleExtractorService,
                "extract_title",
                return_value=None,
            ),
            patch.object(
                file_title_worker.FileAliasNameGeneratorService,
                "generate_alias_name",
            ) as mock_generate_alias,
            patch.object(file_title_worker.KnowledgeFileDao, "update") as mock_update,
        ):
            file_title_worker.extract_knowledge_file_title_celery(2, "preview-key")

        assert db_file.file_name == "old_name.txt"
        assert db_file.alias_name is None
        mock_generate_alias.assert_not_called()
        mock_update.assert_not_called()
        mock_dispatch.assert_called_once_with(**_parse_dispatch_kwargs(2, "preview-key"))

    @patch("bisheng.knowledge.domain.services.knowledge_parse_dispatch_service.dispatch_knowledge_parse_task_sync")
    def test_file_not_found_still_triggers_parse(self, mock_dispatch):
        with patch.object(
            file_title_worker.KnowledgeFileDao,
            "query_by_id_sync",
            return_value=None,
        ):
            file_title_worker.extract_knowledge_file_title_celery(3, "preview-key")

        mock_dispatch.assert_called_once_with(**_parse_dispatch_kwargs(3, "preview-key"))

    @patch("bisheng.knowledge.domain.services.knowledge_parse_dispatch_service.dispatch_knowledge_parse_task_sync")
    def test_download_failure_still_triggers_parse(self, mock_dispatch):
        db_file = MagicMock()
        db_file.id = 4
        db_file.knowledge_id = 1
        db_file.status = KnowledgeFileStatus.WAITING.value
        db_file.file_name = "old_name.pdf"
        db_file.object_name = "original/4.pdf"

        with (
            patch.object(
                file_title_worker.KnowledgeFileDao,
                "query_by_id_sync",
                return_value=db_file,
            ),
            patch.object(
                file_title_worker,
                "download_minio_file",
                side_effect=RuntimeError("download error"),
            ),
        ):
            file_title_worker.extract_knowledge_file_title_celery(4, "preview-key")

        mock_dispatch.assert_called_once_with(**_parse_dispatch_kwargs(4, "preview-key"))
