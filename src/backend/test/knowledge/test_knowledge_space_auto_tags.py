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
    assert KnowledgeSpaceTagLibraryService.normalize_tags(
        [" 政策 ", "", "政策", "制度"]
    ) == ["政策", "政策", "制度"]

    with pytest.raises(KnowledgeSpaceTagLibraryInvalidError):
        KnowledgeSpaceTagLibraryService.normalize_tags([f"tag-{i}" for i in range(201)])


def test_auto_tag_parse_accepts_strict_json_and_json_fence():
    assert KnowledgeSpaceAutoTagService._parse_llm_tags(
        '{"tags": ["政策", "制度"]}'
    ) == ["政策", "制度"]
    assert KnowledgeSpaceAutoTagService._parse_llm_tags(
        '```json\n{"tags": ["项目"]}\n```'
    ) == ["项目"]
    assert KnowledgeSpaceAutoTagService._parse_llm_tags("not-json") == []


def test_auto_tag_match_only_uses_library_tags_and_limits_result_count():
    selected = ["政策", "未知", "制度", "项目", "市场", "财务", "培训"]
    library_tags = ["政策", "制度", "项目", "市场", "财务", "培训"]

    assert KnowledgeSpaceAutoTagService._match_library_tags(selected, library_tags) == [
        "政策",
        "制度",
        "项目",
        "市场",
        "财务",
    ]


def test_auto_tag_should_run_only_for_successful_uploaded_space_file():
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
    )

    assert KnowledgeSpaceAutoTagService._should_run(knowledge, db_file)

    db_file.file_source = FileSource.CHANNEL.value
    assert not KnowledgeSpaceAutoTagService._should_run(knowledge, db_file)

    db_file.file_source = FileSource.UPLOAD.value
    db_file.status = KnowledgeFileStatus.FAILED.value
    assert not KnowledgeSpaceAutoTagService._should_run(knowledge, db_file)

    db_file.status = KnowledgeFileStatus.SUCCESS.value
    knowledge.type = KnowledgeTypeEnum.NORMAL.value
    assert not KnowledgeSpaceAutoTagService._should_run(knowledge, db_file)
