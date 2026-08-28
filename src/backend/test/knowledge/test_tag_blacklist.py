from unittest.mock import AsyncMock, patch

import pytest

from bisheng.common.errcode.tag import (
    TagBlacklistAlreadyExistError,
    TagBlacklistLimitExceededError,
    TagBlacklistNotFoundError,
    TagNameParamsIsEmptyError,
)
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import (
    FileSource,
    FileType,
    KnowledgeFile,
    KnowledgeFileStatus,
)
from bisheng.knowledge.domain.services.knowledge_space_auto_tag_service import KnowledgeSpaceAutoTagService
from bisheng.knowledge.domain.services.tag_blacklist_service import TAG_BLACKLIST_MAX, TagBlacklistService


def test_is_blocked_name_matches_exact_and_similar():
    catalog = [("机密文件", "机密文件"), ("内部制度", "内部制度")]
    assert TagBlacklistService.is_blocked_name("机密文件", catalog)
    assert TagBlacklistService.is_blocked_name("机密文件汇编", catalog)
    assert not TagBlacklistService.is_blocked_name("公开政策", catalog)


def test_filter_unblocked_names_drops_blacklist_and_near_matches():
    catalog = [("涉密", "涉密")]
    kept = TagBlacklistService.filter_unblocked_names(["政策", "涉密", "涉密材料", "制度"], catalog)
    assert kept == ["政策", "制度"]


@pytest.mark.asyncio
async def test_preview_insert_async_reports_cap():
    with (
        patch(
            "bisheng.knowledge.domain.services.tag_blacklist_service.TagBlacklistDao.acount",
            new=AsyncMock(return_value=999),
        ),
        patch(
            "bisheng.knowledge.domain.services.tag_blacklist_service.TagBlacklistDao.alist_existing_name_keys",
            new=AsyncMock(return_value=set()),
        ),
    ):
        preview = await TagBlacklistService.preview_insert_async(["a", "b"])
    assert preview.count == 999
    assert preview.new_count == 2
    assert preview.would_exceed is True
    assert preview.limit == TAG_BLACKLIST_MAX


@pytest.mark.asyncio
async def test_ensure_can_insert_raises_when_over_limit():
    with (
        patch(
            "bisheng.knowledge.domain.services.tag_blacklist_service.TagBlacklistDao.acount",
            new=AsyncMock(return_value=1000),
        ),
        patch(
            "bisheng.knowledge.domain.services.tag_blacklist_service.TagBlacklistDao.alist_existing_name_keys",
            new=AsyncMock(return_value=set()),
        ),
        pytest.raises(TagBlacklistLimitExceededError),
    ):
        await TagBlacklistService.ensure_can_insert_async(["机密"])


@pytest.mark.asyncio
async def test_preview_ignores_names_already_blacklisted():
    with (
        patch(
            "bisheng.knowledge.domain.services.tag_blacklist_service.TagBlacklistDao.acount",
            new=AsyncMock(return_value=1000),
        ),
        patch(
            "bisheng.knowledge.domain.services.tag_blacklist_service.TagBlacklistDao.alist_existing_name_keys",
            new=AsyncMock(return_value={"机密"}),
        ),
    ):
        preview = await TagBlacklistService.preview_insert_async(["机密"])
    assert preview.new_count == 0
    assert preview.would_exceed is False


@pytest.mark.asyncio
async def test_add_name_async_rejects_empty_and_duplicate():
    with pytest.raises(TagNameParamsIsEmptyError):
        await TagBlacklistService.add_name_async("   ", user_id=1)

    with (
        patch(
            "bisheng.knowledge.domain.services.tag_blacklist_service.TagBlacklistDao.alist_existing_name_keys",
            new=AsyncMock(return_value={"机密"}),
        ),
        pytest.raises(TagBlacklistAlreadyExistError),
    ):
        await TagBlacklistService.add_name_async("机密", user_id=1)


@pytest.mark.asyncio
async def test_add_name_async_raises_when_at_limit():
    with (
        patch(
            "bisheng.knowledge.domain.services.tag_blacklist_service.TagBlacklistDao.alist_existing_name_keys",
            new=AsyncMock(return_value=set()),
        ),
        patch(
            "bisheng.knowledge.domain.services.tag_blacklist_service.TagBlacklistDao.acount",
            new=AsyncMock(return_value=1000),
        ),
        pytest.raises(TagBlacklistLimitExceededError),
    ):
        await TagBlacklistService.add_name_async("新词", user_id=1)


@pytest.mark.asyncio
async def test_delete_missing_row_raises():
    with patch(
        "bisheng.knowledge.domain.services.tag_blacklist_service.TagBlacklistDao.aget",
        new=AsyncMock(return_value=None),
    ):
        with pytest.raises(TagBlacklistNotFoundError):
            await TagBlacklistService.delete_async(1)


def test_recommend_filters_blacklisted_candidates_before_llm():
    knowledge = Knowledge(id=1, name="space", type=KnowledgeTypeEnum.SPACE.value, tenant_id=1)
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
    candidates = ["政策", "制度", "机密", "内部", "公开", "流程", "标准", "规范", "指南", "手册", "办法", "细则"]
    with (
        patch.object(KnowledgeSpaceAutoTagService, "_resolve_library_ids", return_value=[10]),
        patch.object(KnowledgeSpaceAutoTagService, "_collect_library_tags", return_value=(candidates, [])),
        patch.object(
            KnowledgeSpaceAutoTagService,
            "_blacklist_catalog",
            return_value=[("机密", "机密"), ("内部", "内部")],
        ),
        patch.object(KnowledgeSpaceAutoTagService, "_invoke_llm") as invoke,
    ):
        names = KnowledgeSpaceAutoTagService.recommend_bound_library_tags_sync(knowledge, db_file)
    invoke.assert_not_called()
    assert names == ["政策", "制度", "公开", "流程", "标准", "规范", "指南", "手册", "办法", "细则"]
