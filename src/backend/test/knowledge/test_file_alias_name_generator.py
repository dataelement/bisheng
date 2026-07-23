from unittest.mock import MagicMock, patch

import pytest  # noqa: F401

from bisheng.knowledge.domain.services.file_alias_name_generator import (
    FileAliasNameGeneratorService,
)


class FakePrompt:
    def __init__(self, system: str, user: str):
        self.system = system
        self.user = user


class FakePromptObj:
    def __init__(self, system: str = "sys", user: str = "user"):
        self.prompt = FakePrompt(system, user)


def _make_llm_response(content: str):
    response = MagicMock()
    response.content = content
    return response


class TestGenerateAliasName:
    @patch("bisheng.knowledge.domain.services.file_alias_name_generator.LLMService.get_knowledge_llm")
    @patch("bisheng.knowledge.domain.services.file_alias_name_generator.LLMService.get_bisheng_llm_sync")
    @patch("bisheng.knowledge.domain.services.file_alias_name_generator.get_prompt_manager_sync")
    def test_success_json(self, mock_get_prompt_manager, mock_get_llm, mock_get_cfg, tmp_path):
        cfg = MagicMock()
        cfg.file_alias_model_id = 42
        mock_get_cfg.return_value = cfg

        llm = MagicMock()
        llm.invoke.return_value = _make_llm_response('{"status":"success","new_file_name":"2024 Q3 Report_v3.pdf"}')
        mock_get_llm.return_value = llm

        prompt_manager = MagicMock()
        prompt_manager.render_prompt.return_value = FakePromptObj()
        mock_get_prompt_manager.return_value = prompt_manager

        file = tmp_path / "report_v3.pdf"
        file.write_text("dummy")

        result = FileAliasNameGeneratorService.generate_alias_name(
            file_path=str(file),
            file_name="report_v3.pdf",
            extracted_title="2024年第三季度财务报告",
            invoke_user_id=1,
            tenant_id=1,
        )
        assert result == "2024 Q3 Report_v3.pdf"

    @patch("bisheng.knowledge.domain.services.file_alias_name_generator.LLMService.get_knowledge_llm")
    @patch("bisheng.knowledge.domain.services.file_alias_name_generator.LLMService.get_bisheng_llm_sync")
    @patch("bisheng.knowledge.domain.services.file_alias_name_generator.get_prompt_manager_sync")
    def test_no_title(self, mock_get_prompt_manager, mock_get_llm, mock_get_cfg, tmp_path):
        cfg = MagicMock()
        cfg.file_alias_model_id = 42
        mock_get_cfg.return_value = cfg

        llm = MagicMock()
        llm.invoke.return_value = _make_llm_response('{"status":"no_title","new_file_name":null}')
        mock_get_llm.return_value = llm

        prompt_manager = MagicMock()
        prompt_manager.render_prompt.return_value = FakePromptObj()
        mock_get_prompt_manager.return_value = prompt_manager

        file = tmp_path / "data.csv"
        file.write_text("name,age\n")

        result = FileAliasNameGeneratorService.generate_alias_name(
            file_path=str(file),
            file_name="data.csv",
            extracted_title="",
            invoke_user_id=1,
            tenant_id=1,
        )
        assert result is None

    @patch("bisheng.knowledge.domain.services.file_alias_name_generator.LLMService.get_knowledge_llm")
    @patch("bisheng.knowledge.domain.services.file_alias_name_generator.LLMService.get_bisheng_llm_sync")
    @patch("bisheng.knowledge.domain.services.file_alias_name_generator.get_prompt_manager_sync")
    def test_json_in_markdown_block(self, mock_get_prompt_manager, mock_get_llm, mock_get_cfg, tmp_path):
        cfg = MagicMock()
        cfg.file_alias_model_id = 42
        mock_get_cfg.return_value = cfg

        llm = MagicMock()
        llm.invoke.return_value = _make_llm_response(
            '```json\n{"status":"success","new_file_name":"Clean Name_v2.docx"}\n```'
        )
        mock_get_llm.return_value = llm

        prompt_manager = MagicMock()
        prompt_manager.render_prompt.return_value = FakePromptObj()
        mock_get_prompt_manager.return_value = prompt_manager

        file = tmp_path / "doc.docx"
        file.write_bytes(b"PK")

        result = FileAliasNameGeneratorService.generate_alias_name(
            file_path=str(file),
            file_name="doc_v2.docx",
            extracted_title="Clean Name",
            invoke_user_id=1,
            tenant_id=1,
        )
        assert result == "Clean Name_v2.docx"

    @patch("bisheng.knowledge.domain.services.file_alias_name_generator.LLMService.get_knowledge_llm")
    @patch("bisheng.knowledge.domain.services.file_alias_name_generator.LLMService.get_bisheng_llm_sync")
    @patch("bisheng.knowledge.domain.services.file_alias_name_generator.get_prompt_manager_sync")
    def test_force_original_extension(self, mock_get_prompt_manager, mock_get_llm, mock_get_cfg, tmp_path):
        cfg = MagicMock()
        cfg.file_alias_model_id = 42
        mock_get_cfg.return_value = cfg

        llm = MagicMock()
        llm.invoke.return_value = _make_llm_response('{"status":"success","new_file_name":"New Name.txt"}')
        mock_get_llm.return_value = llm

        prompt_manager = MagicMock()
        prompt_manager.render_prompt.return_value = FakePromptObj()
        mock_get_prompt_manager.return_value = prompt_manager

        file = tmp_path / "file.pdf"
        file.write_text("dummy")

        result = FileAliasNameGeneratorService.generate_alias_name(
            file_path=str(file),
            file_name="file.pdf",
            extracted_title="New Name",
            invoke_user_id=1,
            tenant_id=1,
        )
        assert result == "New Name.pdf"

    @patch("bisheng.knowledge.domain.services.file_alias_name_generator.LLMService.get_knowledge_llm")
    @patch("bisheng.knowledge.domain.services.file_alias_name_generator.LLMService.get_bisheng_llm_sync")
    @patch("bisheng.knowledge.domain.services.file_alias_name_generator.get_prompt_manager_sync")
    def test_invalid_json_returns_none(self, mock_get_prompt_manager, mock_get_llm, mock_get_cfg, tmp_path):
        cfg = MagicMock()
        cfg.file_alias_model_id = 42
        mock_get_cfg.return_value = cfg

        llm = MagicMock()
        llm.invoke.return_value = _make_llm_response("not json")
        mock_get_llm.return_value = llm

        prompt_manager = MagicMock()
        prompt_manager.render_prompt.return_value = FakePromptObj()
        mock_get_prompt_manager.return_value = prompt_manager

        file = tmp_path / "file.txt"
        file.write_text("dummy")

        result = FileAliasNameGeneratorService.generate_alias_name(
            file_path=str(file),
            file_name="file.txt",
            extracted_title="Title",
            invoke_user_id=1,
            tenant_id=1,
        )
        assert result is None

    @patch("bisheng.knowledge.domain.services.file_alias_name_generator.LLMService.get_knowledge_llm")
    @patch("bisheng.knowledge.domain.services.file_alias_name_generator.LLMService.get_bisheng_llm_sync")
    @patch("bisheng.knowledge.domain.services.file_alias_name_generator.get_prompt_manager_sync")
    def test_llm_exception_returns_none(self, mock_get_prompt_manager, mock_get_llm, mock_get_cfg, tmp_path):
        cfg = MagicMock()
        cfg.file_alias_model_id = 42
        mock_get_cfg.return_value = cfg

        llm = MagicMock()
        llm.invoke.side_effect = RuntimeError("llm error")
        mock_get_llm.return_value = llm

        prompt_manager = MagicMock()
        prompt_manager.render_prompt.return_value = FakePromptObj()
        mock_get_prompt_manager.return_value = prompt_manager

        file = tmp_path / "file.txt"
        file.write_text("dummy")

        result = FileAliasNameGeneratorService.generate_alias_name(
            file_path=str(file),
            file_name="file.txt",
            extracted_title="Title",
            invoke_user_id=1,
            tenant_id=1,
        )
        assert result is None

    @patch("bisheng.knowledge.domain.services.file_alias_name_generator.LLMService.get_knowledge_llm")
    def test_missing_model_config_returns_none(self, mock_get_cfg, tmp_path):
        cfg = MagicMock()
        cfg.file_alias_model_id = None
        mock_get_cfg.return_value = cfg

        file = tmp_path / "file.txt"
        file.write_text("dummy")

        result = FileAliasNameGeneratorService.generate_alias_name(
            file_path=str(file),
            file_name="file.txt",
            extracted_title="Title",
            invoke_user_id=1,
            tenant_id=1,
        )
        assert result is None


class TestReadTextSnippet:
    def test_reads_text_like_file(self, tmp_path):
        file = tmp_path / "doc.txt"
        file.write_text("Line one\nLine two\n", encoding="utf-8")
        snippet = FileAliasNameGeneratorService._read_text_snippet(str(file))
        assert snippet.startswith("Line one")

    def test_skips_binary_file(self, tmp_path):
        file = tmp_path / "doc.pdf"
        file.write_bytes(b"\x00\x01\x02")
        snippet = FileAliasNameGeneratorService._read_text_snippet(str(file))
        assert snippet == ""
