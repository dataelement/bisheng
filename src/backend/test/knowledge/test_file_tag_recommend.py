from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.documents import Document

from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import (
    FileSource,
    FileType,
    KnowledgeFile,
    KnowledgeFileStatus,
)
from bisheng.knowledge.domain.services.knowledge_space_auto_tag_service import (
    RECOMMENDED_TAGS_METADATA_KEY,
    KnowledgeSpaceAutoTagService,
)
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService


@pytest.fixture(autouse=True)
def _empty_tag_blacklist():
    with patch.object(KnowledgeSpaceAutoTagService, "_blacklist_catalog", return_value=[]):
        yield


def _space_file(**kwargs) -> KnowledgeFile:
    defaults = dict(
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
    defaults.update(kwargs)
    return KnowledgeFile(**defaults)


def test_recommend_bound_library_tags_sync_returns_up_to_ten():
    knowledge = Knowledge(id=1, name="space", type=KnowledgeTypeEnum.SPACE.value, tenant_id=1)
    db_file = _space_file()
    module_path = "bisheng.knowledge.domain.services.knowledge_space_auto_tag_service"
    candidates = [f"标签{i}" for i in range(12)]

    with (
        patch.object(KnowledgeSpaceAutoTagService, "_resolve_library_ids", return_value=[10]),
        patch.object(KnowledgeSpaceAutoTagService, "_collect_library_tags", return_value=(candidates, [])),
        patch(
            f"{module_path}.LLMService.get_knowledge_llm",
            return_value=SimpleNamespace(extract_title_model_id=123),
        ),
        patch(f"{module_path}.LLMService.get_bisheng_llm_sync", return_value=object()),
        patch.object(
            KnowledgeSpaceAutoTagService,
            "_invoke_llm",
            return_value=candidates,
        ),
    ):
        names = KnowledgeSpaceAutoTagService.recommend_bound_library_tags_sync(
            knowledge,
            db_file,
            exclude_names=["标签0"],
            documents=[Document(page_content="文章正文")],
        )

    assert names == [f"标签{i}" for i in range(1, 11)]


def test_recommend_bound_library_tags_sync_fills_to_ten_when_llm_returns_fewer():
    knowledge = Knowledge(id=1, name="space", type=KnowledgeTypeEnum.SPACE.value, tenant_id=1)
    db_file = _space_file()
    module_path = "bisheng.knowledge.domain.services.knowledge_space_auto_tag_service"
    candidates = [f"标签{i}" for i in range(12)]

    with (
        patch.object(KnowledgeSpaceAutoTagService, "_resolve_library_ids", return_value=[10]),
        patch.object(KnowledgeSpaceAutoTagService, "_collect_library_tags", return_value=(candidates, [])),
        patch(
            f"{module_path}.LLMService.get_knowledge_llm",
            return_value=SimpleNamespace(extract_title_model_id=123),
        ),
        patch(f"{module_path}.LLMService.get_bisheng_llm_sync", return_value=object()),
        patch.object(
            KnowledgeSpaceAutoTagService,
            "_invoke_llm",
            return_value=["标签2", "标签5"],
        ) as invoke,
    ):
        names = KnowledgeSpaceAutoTagService.recommend_bound_library_tags_sync(
            knowledge,
            db_file,
            documents=[Document(page_content="文章正文")],
        )

    invoke.assert_called_once()
    assert names[:2] == ["标签2", "标签5"]
    assert len(names) == 10
    assert len(set(names)) == 10
    assert set(names) <= set(candidates)


def test_recommend_bound_library_tags_sync_returns_all_when_candidates_fewer_than_ten():
    knowledge = Knowledge(id=1, name="space", type=KnowledgeTypeEnum.SPACE.value, tenant_id=1)
    db_file = _space_file()
    candidates = [f"标签{i}" for i in range(6)]

    with (
        patch.object(KnowledgeSpaceAutoTagService, "_resolve_library_ids", return_value=[10]),
        patch.object(KnowledgeSpaceAutoTagService, "_collect_library_tags", return_value=(candidates, [])),
        patch.object(
            KnowledgeSpaceAutoTagService,
            "_invoke_llm",
        ) as invoke,
    ):
        names = KnowledgeSpaceAutoTagService.recommend_bound_library_tags_sync(
            knowledge,
            db_file,
            exclude_names=["标签0"],
            documents=[Document(page_content="文章正文")],
        )

    invoke.assert_not_called()
    assert names == ["标签1", "标签2", "标签3", "标签4", "标签5"]


def test_recommend_bound_library_tags_sync_skips_llm_when_exactly_ten_candidates():
    knowledge = Knowledge(id=1, name="space", type=KnowledgeTypeEnum.SPACE.value, tenant_id=1)
    db_file = _space_file()
    candidates = [f"标签{i}" for i in range(10)]

    with (
        patch.object(KnowledgeSpaceAutoTagService, "_resolve_library_ids", return_value=[10]),
        patch.object(KnowledgeSpaceAutoTagService, "_collect_library_tags", return_value=(candidates, [])),
        patch.object(
            KnowledgeSpaceAutoTagService,
            "_invoke_llm",
        ) as invoke,
    ):
        names = KnowledgeSpaceAutoTagService.recommend_bound_library_tags_sync(
            knowledge,
            db_file,
            documents=[Document(page_content="文章正文")],
        )

    invoke.assert_not_called()
    assert names == candidates


def test_recommend_bound_library_tags_sync_empty_without_binding():
    knowledge = Knowledge(id=1, name="space", type=KnowledgeTypeEnum.SPACE.value, tenant_id=1)
    db_file = _space_file()
    with patch.object(KnowledgeSpaceAutoTagService, "_resolve_library_ids", return_value=[]):
        assert KnowledgeSpaceAutoTagService.recommend_bound_library_tags_sync(knowledge, db_file) == []


def test_generate_recommended_tags_after_parse_excludes_applied_and_stores_cache():
    knowledge = Knowledge(id=1, name="space", type=KnowledgeTypeEnum.SPACE.value, tenant_id=1)
    db_file = _space_file()
    documents = [Document(page_content="文章正文")]

    with (
        patch.object(
            KnowledgeSpaceAutoTagService,
            "_list_file_applied_tag_names",
            return_value=["已打"],
        ) as list_applied,
        patch.object(
            KnowledgeSpaceAutoTagService,
            "recommend_bound_library_tags_sync",
            return_value=["推荐1", "推荐2"],
        ) as recommend,
    ):
        names = KnowledgeSpaceAutoTagService.generate_recommended_tags_after_parse(
            knowledge,
            db_file,
            documents=documents,
        )

    list_applied.assert_called_once_with(2)
    recommend.assert_called_once()
    assert recommend.call_args.kwargs["exclude_names"] == ["已打"]
    assert recommend.call_args.kwargs["documents"] is documents
    assert names == ["推荐1", "推荐2"]
    assert db_file.user_metadata[RECOMMENDED_TAGS_METADATA_KEY] == ["推荐1", "推荐2"]


def _recommend_service_fixtures():
    service = KnowledgeSpaceService.__new__(KnowledgeSpaceService)
    service._require_read_permission = AsyncMock()
    knowledge = Knowledge(id=8, name="space", type=KnowledgeTypeEnum.SPACE.value)
    db_file = KnowledgeFile(id=3, knowledge_id=8, abstract="body")
    space_tags = [
        {"name": "政策", "id": 1, "resource_type": "system_tag"},
        {"name": "制度", "id": 2, "resource_type": "manual_tag"},
        {"name": "其他", "id": 3, "resource_type": "manual_tag"},
        {"name": "已打", "id": 4, "resource_type": "manual_tag"},
    ]
    return service, knowledge, db_file, space_tags


@pytest.mark.asyncio
async def test_recommend_file_tags_maps_space_tag_payloads():
    service, knowledge, db_file, space_tags = _recommend_service_fixtures()
    db_file.user_metadata = {RECOMMENDED_TAGS_METADATA_KEY: ["政策", "制度"]}

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.query_by_id",
            new=AsyncMock(return_value=db_file),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id",
            new=AsyncMock(return_value=knowledge),
        ),
        patch.object(
            KnowledgeSpaceAutoTagService,
            "recommend_bound_library_tags_sync",
        ) as recommend,
        patch.object(
            service,
            "get_space_tags",
            new=AsyncMock(return_value=space_tags),
        ),
    ):
        result = await service.recommend_file_tags(8, 3, exclude_names=["忽略"])

    recommend.assert_not_called()
    assert [item["name"] for item in result] == ["政策", "制度"]


@pytest.mark.asyncio
async def test_recommend_file_tags_uses_parse_cache_without_llm():
    service, knowledge, db_file, space_tags = _recommend_service_fixtures()
    db_file.user_metadata = {RECOMMENDED_TAGS_METADATA_KEY: ["政策", "制度", "已打"]}

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.query_by_id",
            new=AsyncMock(return_value=db_file),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id",
            new=AsyncMock(return_value=knowledge),
        ),
        patch.object(
            KnowledgeSpaceAutoTagService,
            "recommend_bound_library_tags_sync",
        ) as recommend,
        patch.object(
            service,
            "get_space_tags",
            new=AsyncMock(return_value=space_tags),
        ),
    ):
        result = await service.recommend_file_tags(8, 3, exclude_names=[])

    recommend.assert_not_called()
    assert [item["name"] for item in result] == ["政策", "制度", "已打"]


@pytest.mark.asyncio
async def test_recommend_file_tags_cache_keeps_selected_and_applied_names():
    service, knowledge, db_file, space_tags = _recommend_service_fixtures()
    db_file.user_metadata = {RECOMMENDED_TAGS_METADATA_KEY: ["政策", "制度"]}

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.query_by_id",
            new=AsyncMock(return_value=db_file),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id",
            new=AsyncMock(return_value=knowledge),
        ),
        patch.object(
            KnowledgeSpaceAutoTagService,
            "recommend_bound_library_tags_sync",
        ) as recommend,
        patch.object(
            service,
            "get_space_tags",
            new=AsyncMock(return_value=space_tags),
        ),
    ):
        result = await service.recommend_file_tags(8, 3, exclude_names=["制度"])

    recommend.assert_not_called()
    assert [item["name"] for item in result] == ["政策", "制度"]


@pytest.mark.asyncio
async def test_recommend_file_tags_returns_empty_without_cache_and_without_generating():
    service, knowledge, db_file, space_tags = _recommend_service_fixtures()

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.query_by_id",
            new=AsyncMock(return_value=db_file),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id",
            new=AsyncMock(return_value=knowledge),
        ),
        patch.object(
            KnowledgeSpaceAutoTagService,
            "recommend_bound_library_tags_sync",
        ) as recommend,
        patch.object(
            service,
            "get_space_tags",
            new=AsyncMock(return_value=space_tags),
        ),
    ):
        result = await service.recommend_file_tags(8, 3)

    recommend.assert_not_called()
    assert result == []


@pytest.mark.asyncio
async def test_recommend_file_tags_refresh_reruns_llm_and_updates_cache():
    service, knowledge, db_file, space_tags = _recommend_service_fixtures()
    db_file.user_metadata = {RECOMMENDED_TAGS_METADATA_KEY: ["旧推荐"]}

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.query_by_id",
            new=AsyncMock(return_value=db_file),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id",
            new=AsyncMock(return_value=knowledge),
        ),
        patch.object(
            KnowledgeSpaceAutoTagService,
            "_list_file_applied_tag_names",
            return_value=["已打"],
        ),
        patch.object(
            KnowledgeSpaceAutoTagService,
            "recommend_bound_library_tags_sync",
            return_value=["政策"],
        ) as recommend,
        patch.object(
            KnowledgeSpaceAutoTagService,
            "persist_recommended_tag_names",
        ) as persist,
        patch.object(
            service,
            "get_space_tags",
            new=AsyncMock(return_value=space_tags),
        ),
    ):
        result = await service.recommend_file_tags(8, 3, exclude_names=["忽略"], refresh=True)

    recommend.assert_called_once()
    assert set(recommend.call_args.kwargs["exclude_names"]) == {"忽略", "已打"}
    persist.assert_called_once()
    assert persist.call_args.args[1] == ["政策"]
    assert [item["name"] for item in result] == ["政策"]
