from contextlib import asynccontextmanager
from datetime import datetime, timezone
from time import monotonic
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.schemas.knowledge_space_schema import (
    ShougangPortalFileBrowseReq,
    ShougangPortalFileCountReq,
)
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

MODULE = "bisheng.knowledge.domain.services.knowledge_space_service"


def setup_case(monkeypatch, failure=None):
    state = {"cold_reads": 0, "writes": [], "pool_reads": 0, "interest_reads": 0, "domain_reads": 0, "recent_reads": 0}
    state["cache_ids"] = [(10, i) for i in range(1, 21)]
    records = [
        SimpleNamespace(
            space_id=10,
            file_id=i,
            recommendable=True,
            source_update_time=datetime(2026, 9, 1, tzinfo=timezone.utc),
            business_domain_code="PP",
            permission_scope="inherited",
        )
        for i in range(1, 23)
    ]
    files = [
        KnowledgeFile(
            id=i,
            knowledge_id=10,
            file_type=1,
            status=2,
            user_id=1,
            user_name="tester",
            file_name=f"文档{i}.pdf",
            reference_document_id=1000 + i,
            entry_type="manager",
            entry_status="active",
            abstract=f"摘要{i}",
            file_encoding=f"SGGF-POL-PP-202609-{i:06d}",
        )
        for i in range(1, 23)
    ]
    if failure == "file_deleted":
        files = [file for file in files if file.id != 20]

    class Redis:
        async def get_behavior_version(self, *_args):
            return 1

        async def get_pool_state(self, *_args):
            return SimpleNamespace(active_pool_version="pool-1")

        async def is_pool_version_ready(self, *_args):
            return True

        async def get_top_n(self, *_args, **_kwargs):
            assert (*_args, _kwargs["scope"]) == (1, 7, 3, "pool-1", 1, "base")
            if failure == "cache_missing":
                return None
            if failure == "cache_empty":
                return []
            if failure == "redis_down":
                raise TimeoutError("Redis unavailable")
            return list(state["cache_ids"])

        async def get_user_domains(self, *_args):
            state["domain_reads"] += 1
            return []

        async def get_interest(self, *_args):
            state["interest_reads"] += 1
            return []

        async def get_pool(self, *_args, **_kwargs):
            state["pool_reads"] += 1
            return []

        async def list_recent_reads(self, *_args, **_kwargs):
            state["recent_reads"] += 1
            return {}

        async def set_top_n(self, *_args, **_kwargs):
            if failure == "redis_down":
                raise TimeoutError("Redis unavailable")
            state["writes"].append(_args[5])
            state["cache_ids"] = list(_args[5])

    class Projection:
        async def find_by_file_ids(self, ids):
            return [
                record
                for record in records
                if record.file_id in ids and not (failure == "record_missing" and record.file_id == 20)
            ]

        async def list_latest_recommendable(self, **_kwargs):
            state["cold_reads"] += 1
            if failure is None:
                raise AssertionError("有效缓存不能读取其他推荐候选")
            return [record for record in records if not (failure == "record_missing" and record.file_id == 20)]

    @asynccontextmanager
    async def session_factory():
        yield Mock()

    config = SimpleNamespace(
        version=3,
        portal=SimpleNamespace(
            recommendation=SimpleNamespace(
                home_total_count=20, stable_shuffle_score_gap=5, stable_shuffle_cycle_days=7
            ),
            display=SimpleNamespace(home=SimpleNamespace(section_page_size=6)),
            domains=[],
        ),
    )
    monkeypatch.setattr(f"{MODULE}.get_async_db_session", session_factory)
    monkeypatch.setattr(f"{MODULE}.get_current_tenant_id", lambda: 1)
    monkeypatch.setattr(f"{MODULE}.PortalRecommendationRedisRepositoryImpl", Redis)
    monkeypatch.setattr(f"{MODULE}.PortalRecommendationRepositoryImpl", lambda _session: Projection())
    monkeypatch.setattr(f"{MODULE}.ShougangPortalConfigService.get_config", AsyncMock(return_value=config))
    bindings = (
        [{"resource_type": "knowledge_file", "resource_id": "20", "relation": "viewer"}]
        if failure == "public_acl_revoked"
        else []
    )
    monkeypatch.setattr(
        f"{MODULE}.PortalRecommendationProjectionService.load_bindings_strict", AsyncMock(return_value=bindings)
    )

    async def current_files(**kwargs):
        return [
            file for file in files if file.id in kwargs["file_ids"] and file.knowledge_id in kwargs["knowledge_ids"]
        ]

    monkeypatch.setattr(f"{MODULE}.KnowledgeFileDao.aget_file_by_space_filters", current_files)
    service = KnowledgeSpaceService(request=Mock(headers={}), login_user=SimpleNamespace(user_id=7, tenant_id=1))
    if failure == "non_primary":
        service.version_repo = SimpleNamespace(
            find_non_primary_file_ids_by_knowledge_ids=AsyncMock(return_value=[20]),
        )
    spaces = [SimpleNamespace(id=10, name="当前知识库")]
    service._portal_space_kind_map = {10: "public"}
    service._filter_non_personal_recommendation_spaces = AsyncMock(return_value=(spaces, 0, 0))
    service._get_shougang_portal_public_space_ids = AsyncMock(
        return_value={10} if failure == "public_acl_revoked" else set()
    )
    service._public_space_viewer_permission_ids = AsyncMock(return_value={"view_file", "download_file"})
    service.resolve_portal_discovery = AsyncMock(
        return_value=SimpleNamespace(
            discoverable_space_ids=[]
            if failure in {"permission_denied", "engine_failed", "public_acl_revoked"}
            else [10],
        )
    )
    service._build_child_permission_context = AsyncMock(
        side_effect=RuntimeError("unavailable") if failure == "engine_failed" else None,
        return_value={},
    )

    async def permission(file, **_kwargs):
        return set() if file.id == 20 and failure in {"permission_denied", "public_acl_revoked"} else {"view_file"}

    service._get_child_item_effective_permission_ids = permission

    async def distribution(items, **_kwargs):
        return {
            item.id: {"canonical_document_id": 1000 + item.id, "canonical_version_id": 2000 + item.id} for item in items
        }

    service._load_document_distribution_info = AsyncMock(side_effect=distribution)
    service._load_file_tags_batch = AsyncMock(return_value={})
    service._find_pending_publish_approval_file_ids = AsyncMock(return_value=set())
    service._resolve_shougang_portal_source_paths = AsyncMock(return_value=({}, {}))
    service.get_logo_share_link = Mock(return_value="")
    return service, spaces, state


async def test_valid_cache_skips_candidate_prep_and_home_preserves_complete_more_list(monkeypatch):
    service, spaces, state = setup_case(monkeypatch)
    home = await service._recommend_shougang_portal_files(
        req=ShougangPortalFileBrowseReq(recommendation="personalized_v1", response_scene="home"),
        spaces=spaces,
    )
    assert [item["id"] for item in home["data"]] == list(range(1, 7))
    assert home["data"][0]["canonical_document_id"] == 1001
    assert home["data"][0]["canonical_version_id"] == 2001
    assert len(service._load_document_distribution_info.await_args.args[0]) == 6
    service._load_file_tags_batch.assert_not_awaited()
    service._find_pending_publish_approval_file_ids.assert_not_awaited()
    service._resolve_shougang_portal_source_paths.assert_not_awaited()
    assert len(state["writes"][-1]) == 20
    full = await service._recommend_shougang_portal_files(
        req=ShougangPortalFileBrowseReq(recommendation="personalized_v1"),
        spaces=spaces,
    )
    assert [item["id"] for item in full["data"]] == list(range(1, 21))
    assert state["cold_reads"] == state["pool_reads"] == state["interest_reads"] == 0
    assert state["domain_reads"] == state["recent_reads"] == 0
    service._load_file_tags_batch.assert_awaited_once()
    service._resolve_shougang_portal_source_paths.assert_awaited_once()


@pytest.mark.parametrize(
    "failure",
    ["record_missing", "file_deleted", "non_primary", "permission_denied", "public_acl_revoked", "engine_failed"],
)
async def test_invalid_cache_rebuilds_or_fails_closed_without_poisoning_cache(monkeypatch, failure):
    service, spaces, state = setup_case(monkeypatch, failure)
    result = await service._recommend_shougang_portal_files(
        req=ShougangPortalFileBrowseReq(recommendation="personalized_v1"),
        spaces=spaces,
    )
    assert state["cold_reads"] == 1
    ids = [item["id"] for item in result["data"]]
    if failure == "engine_failed":
        assert ids == [] and state["writes"] == []
    else:
        assert len(ids) == 20 and 20 not in ids
        assert len(state["writes"][-1]) == 20


@pytest.mark.parametrize("failure", ["cache_missing", "cache_empty", "redis_down"])
async def test_missing_cache_and_redis_failure_keep_existing_cold_start(monkeypatch, failure):
    service, spaces, state = setup_case(monkeypatch, failure)
    result = await service._recommend_shougang_portal_files(
        req=ShougangPortalFileBrowseReq(recommendation="personalized_v1", response_scene="home"),
        spaces=spaces,
    )
    assert len(result["data"]) == 6 and state["cold_reads"] == 1
    if failure == "redis_down":
        assert state["writes"] == []
    else:
        assert len(state["writes"][-1]) == 20


async def test_cold_preparation_does_not_spend_or_reset_authorization_budget(monkeypatch):
    service, spaces, _state = setup_case(monkeypatch, "force_cold")
    request = ShougangPortalFileBrowseReq(recommendation="personalized_v1")
    context = await service._build_personalized_recommendation_authorizer(req=request, spaces=spaces)
    context["state"].started_at = monotonic() - 2.1
    context["paused_at"] = monotonic() - 2
    service._try_personalized_recommendation_cache = AsyncMock(return_value=(None, context))
    result = await service._recommend_shougang_portal_files(req=request, spaces=spaces)
    assert len(result["data"]) == 20
    assert context["state"].checks == 20
    assert not context["state"].time_budget_reached


async def test_recommendation_count_forces_full_list_scene():
    service = object.__new__(KnowledgeSpaceService)
    service._portal_discovery_result = None
    service.browse_shougang_portal_files = AsyncMock(
        return_value={
            "data": [{"id": i} for i in range(1, 21)],
            "has_more": False,
            "next_cursor": None,
        }
    )
    result = await service.count_shougang_portal_files(
        ShougangPortalFileCountReq(
            query_type="recommendation",
            recommendation="personalized_v1",
            response_scene="home",
        )
    )
    assert result["total"] == 20
    assert service.browse_shougang_portal_files.await_args.args[0].response_scene == "list"
