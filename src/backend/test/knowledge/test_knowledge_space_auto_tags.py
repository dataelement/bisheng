from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from bisheng.common.errcode.knowledge import KnowledgeSpaceTagLibraryInvalidError
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import (
    FileSource,
    FileType,
    KnowledgeFile,
    KnowledgeFileStatus,
)
from bisheng.knowledge.domain.services.knowledge_space_auto_tag_service import (
    KnowledgeSpaceAutoTagService,
)
from bisheng.knowledge.domain.services.knowledge_space_tag_library_service import (
    KnowledgeSpaceTagLibraryService,
)


def test_tag_library_normalize_preserves_duplicates_and_rejects_over_limit():
    assert KnowledgeSpaceTagLibraryService.normalize_tags([" 政策 ", "", "政策", "制度"]) == ["政策", "政策", "制度"]

    with pytest.raises(KnowledgeSpaceTagLibraryInvalidError):
        KnowledgeSpaceTagLibraryService.normalize_tags([f"tag-{i}" for i in range(1000)])


def test_auto_tag_parse_accepts_strict_json_and_json_fence():
    assert KnowledgeSpaceAutoTagService._parse_llm_tags('{"tags": ["政策", "制度"]}') == ["政策", "制度"]
    assert KnowledgeSpaceAutoTagService._parse_llm_tags('```json\n{"tags": ["项目"]}\n```') == ["项目"]
    assert KnowledgeSpaceAutoTagService._parse_llm_tags("not-json") == []


def test_auto_tag_match_only_uses_library_tags_and_limits_result_count():
    selected = ["政策", "未知", "制度", "项目", "市场", "财务", "培训"]
    library_tags = ["政策", "制度", "项目", "市场", "财务", "培训"]

    matched, ai_matched = KnowledgeSpaceAutoTagService._match_library_tags(selected, library_tags, [])
    assert matched == ["政策", "制度", "项目", "市场", "财务"]
    assert ai_matched == []

    selected_with_ai = ["政策", "AI-政策"]
    matched, ai_matched = KnowledgeSpaceAutoTagService._match_library_tags(selected_with_ai, ["政策"], ["AI-政策"])
    assert matched == ["政策"]
    assert ai_matched == ["AI-政策"]

    library_tags = ["政策", "制度", "项目", "市场", "财务"]
    ai_tag_names = [f"AI-{i}" for i in range(7)]
    selected = library_tags + ai_tag_names
    matched, ai_matched = KnowledgeSpaceAutoTagService._match_library_tags(
        selected,
        library_tags,
        ai_tag_names,
    )
    assert matched == library_tags
    assert ai_matched == [f"AI-{i}" for i in range(5)]


_LINK_DAO_PATCH = (
    "bisheng.knowledge.domain.services.knowledge_space_auto_tag_service."
    "KnowledgeTagLibraryLinkDao.list_library_ids_by_knowledge"
)


def test_auto_tag_should_run_only_for_successful_uploaded_space_file():
    knowledge = Knowledge(
        id=1,
        name="space",
        type=KnowledgeTypeEnum.SPACE.value,
        auto_tag_enabled=False,
        auto_tag_library_id=10,
    )
    db_file = KnowledgeFile(
        id=2,
        knowledge_id=1,
        file_name="a.txt",
        file_type=FileType.FILE.value,
        file_source=FileSource.UPLOAD.value,
        status=KnowledgeFileStatus.SUCCESS.value,
    )

    with patch(_LINK_DAO_PATCH, return_value=[]):
        assert KnowledgeSpaceAutoTagService._should_run(knowledge, db_file)

        db_file.file_source = FileSource.CHANNEL.value
        assert not KnowledgeSpaceAutoTagService._should_run(knowledge, db_file)

        db_file.file_source = FileSource.UPLOAD.value
        db_file.status = KnowledgeFileStatus.FAILED.value
        assert not KnowledgeSpaceAutoTagService._should_run(knowledge, db_file)

        db_file.status = KnowledgeFileStatus.SUCCESS.value
        knowledge.type = KnowledgeTypeEnum.NORMAL.value
        assert not KnowledgeSpaceAutoTagService._should_run(knowledge, db_file)


def test_auto_tag_should_skip_manual_upload_tags():
    knowledge = Knowledge(
        id=1,
        name="space",
        type=KnowledgeTypeEnum.SPACE.value,
        auto_tag_enabled=True,
        auto_tag_library_id=10,
    )
    db_file = KnowledgeFile(
        id=2,
        knowledge_id=1,
        file_name="a.txt",
        file_type=FileType.FILE.value,
        file_source=FileSource.UPLOAD.value,
        status=KnowledgeFileStatus.SUCCESS.value,
        user_metadata={"manual_upload_tags_applied": True},
    )

    with patch(_LINK_DAO_PATCH, return_value=[]):
        assert not KnowledgeSpaceAutoTagService._should_run(knowledge, db_file)


def test_auto_tag_llm_uses_zero_temperature():
    knowledge = Knowledge(
        id=1,
        name="space",
        type=KnowledgeTypeEnum.SPACE.value,
        auto_tag_enabled=True,
        auto_tag_library_id=10,
    )
    db_file = KnowledgeFile(
        id=2,
        knowledge_id=1,
        file_name="a.txt",
        file_type=FileType.FILE.value,
        file_source=FileSource.UPLOAD.value,
        status=KnowledgeFileStatus.SUCCESS.value,
        user_id=7,
        tenant_id=1,
        abstract="政策制度内容",
    )
    module_path = "bisheng.knowledge.domain.services.knowledge_space_auto_tag_service"

    with (
        patch.object(KnowledgeSpaceAutoTagService, "_should_run", return_value=True),
        patch.object(KnowledgeSpaceAutoTagService, "_resolve_library_ids", return_value=[10]),
        patch.object(KnowledgeSpaceAutoTagService, "_collect_library_tags", return_value=(["政策"], [])),
        patch(
            f"{module_path}.LLMService.get_knowledge_llm",
            return_value=SimpleNamespace(auto_tag_enabled=True, extract_title_model_id=123, auto_tag_prompt=""),
        ),
        patch(f"{module_path}.LLMService.get_bisheng_llm_sync", return_value=object()) as get_llm,
        patch.object(KnowledgeSpaceAutoTagService, "_invoke_llm", return_value=["政策"]),
        patch.object(KnowledgeSpaceAutoTagService, "_append_file_tags") as append_file_tags,
    ):
        KnowledgeSpaceAutoTagService.apply_after_upload_parse(knowledge, db_file)

    assert get_llm.call_args.kwargs["temperature"] == 0
    append_file_tags.assert_called_once()


def test_auto_tag_should_run_even_when_space_auto_tag_disabled():
    knowledge = Knowledge(
        id=1,
        name="space",
        type=KnowledgeTypeEnum.SPACE.value,
        auto_tag_enabled=False,
        auto_tag_library_id=10,
    )
    db_file = KnowledgeFile(
        id=2,
        knowledge_id=1,
        file_name="a.txt",
        file_type=FileType.FILE.value,
        file_source=FileSource.UPLOAD.value,
        status=KnowledgeFileStatus.SUCCESS.value,
    )

    with patch(_LINK_DAO_PATCH, return_value=[]):
        assert KnowledgeSpaceAutoTagService._should_run(knowledge, db_file)


def test_auto_tag_should_run_when_no_explicit_library_uses_default_fallback():
    """Space with no bound library still runs link A via the default library fallback."""
    knowledge = Knowledge(
        id=1,
        name="space",
        type=KnowledgeTypeEnum.SPACE.value,
        auto_tag_enabled=False,
        auto_tag_library_id=None,
    )
    db_file = KnowledgeFile(
        id=2,
        knowledge_id=1,
        file_name="a.txt",
        file_type=FileType.FILE.value,
        file_source=FileSource.UPLOAD.value,
        status=KnowledgeFileStatus.SUCCESS.value,
    )

    with patch(_LINK_DAO_PATCH, return_value=[]):
        assert KnowledgeSpaceAutoTagService._resolve_library_ids(knowledge) == [1]
        assert KnowledgeSpaceAutoTagService._should_run(knowledge, db_file)


def test_auto_tag_writes_ai_matches_even_when_manual_match_empty():
    """Regression: an empty manual/system match must not skip AI-tag writes."""
    knowledge = Knowledge(
        id=1,
        name="space",
        type=KnowledgeTypeEnum.SPACE.value,
        auto_tag_enabled=False,
        auto_tag_library_id=10,
    )
    db_file = KnowledgeFile(
        id=2,
        knowledge_id=1,
        file_name="a.txt",
        file_type=FileType.FILE.value,
        file_source=FileSource.UPLOAD.value,
        status=KnowledgeFileStatus.SUCCESS.value,
        user_id=7,
        tenant_id=1,
        abstract="ai only content",
    )
    module_path = "bisheng.knowledge.domain.services.knowledge_space_auto_tag_service"

    with (
        patch.object(KnowledgeSpaceAutoTagService, "_should_run", return_value=True),
        patch.object(KnowledgeSpaceAutoTagService, "_resolve_library_ids", return_value=[10]),
        patch.object(KnowledgeSpaceAutoTagService, "_collect_library_tags", return_value=([], ["AI-标签"])),
        patch(
            f"{module_path}.LLMService.get_knowledge_llm",
            return_value=SimpleNamespace(auto_tag_enabled=True, extract_title_model_id=123, auto_tag_prompt=""),
        ),
        patch(f"{module_path}.LLMService.get_bisheng_llm_sync", return_value=object()),
        patch.object(KnowledgeSpaceAutoTagService, "_invoke_llm", return_value=["AI-标签"]),
        patch.object(KnowledgeSpaceAutoTagService, "_cap_ai_tags_for_file", side_effect=lambda _fid, tags: tags),
        patch.object(KnowledgeSpaceAutoTagService, "_append_file_tags") as append_file_tags,
    ):
        KnowledgeSpaceAutoTagService.apply_after_upload_parse(knowledge, db_file)

    append_file_tags.assert_called_once()
    assert append_file_tags.call_args.kwargs["tag_names"] == ["AI-标签"]


def test_cap_ai_tags_for_file_respects_existing_ai_tag_count():
    with patch.object(KnowledgeSpaceAutoTagService, "_count_file_ai_auto_tags", return_value=3):
        capped = KnowledgeSpaceAutoTagService._cap_ai_tags_for_file(99, ["A", "B", "C"])
    assert capped == ["A", "B"]

    with patch.object(KnowledgeSpaceAutoTagService, "_count_file_ai_auto_tags", return_value=5):
        assert KnowledgeSpaceAutoTagService._cap_ai_tags_for_file(99, ["A"]) == []


def test_count_file_ai_auto_tags_includes_pending_review_tags():
    module_path = "bisheng.knowledge.domain.services.knowledge_space_auto_tag_service"
    session = MagicMock()
    session.exec.side_effect = [SimpleNamespace(one=lambda: 2), SimpleNamespace(one=lambda: 3)]
    ctx = MagicMock()
    ctx.__enter__.return_value = session

    with patch(f"{module_path}.get_sync_db_session", return_value=ctx):
        assert KnowledgeSpaceAutoTagService._count_file_ai_auto_tags(42) == 5
