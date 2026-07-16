# ruff: noqa: E402

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

_BACKEND = Path(__file__).resolve().parents[2]
sys.modules["bisheng.worker"].__path__ = [str(_BACKEND / "bisheng/worker")]
sys.modules["bisheng.worker.knowledge"].__path__ = [str(_BACKEND / "bisheng/worker/knowledge")]

from bisheng.core.context.tenant import current_tenant_id
from bisheng.knowledge.domain.services.portal_recommendation_behavior_service import (
    PortalRecommendationBehaviorService,
)
from bisheng.knowledge.domain.services.portal_recommendation_projection_service import (
    PortalRecommendationProjectionService,
    PortalRecommendationSourceFile,
)
from bisheng.knowledge.domain.services.portal_recommendation_service import (
    PortalRecommendationCandidate,
)
from bisheng.worker.knowledge.portal_recommendation import (
    _assemble_rotated_pool,
    _delete_orphan_projection_page,
    _dispatch_task_for_tenants,
    _pool_counts_match,
    _projection_version_for_event,
    _rebuild_user_interest_async,
    recommendation_config_fingerprint,
)


def test_acl_event_version_advances_projection_even_when_file_time_is_unchanged():
    source = PortalRecommendationSourceFile(
        file_id=1,
        space_id=2,
        file_type=1,
        status=2,
        split_rule=None,
        file_encoding=None,
        file_level_path=None,
        source_update_time=datetime(2026, 7, 1, tzinfo=timezone.utc),
        is_primary=True,
    )
    service = SimpleNamespace(
        projection_version_for=PortalRecommendationProjectionService.projection_version_for
    )
    event_version = int(datetime(2026, 7, 15, tzinfo=timezone.utc).timestamp() * 1_000_000)

    assert _projection_version_for_event(service, source, event_version) == event_version


@pytest.mark.asyncio
async def test_full_reconcile_deletes_only_orphan_projections_idempotently():
    projection_repository = SimpleNamespace(delete=AsyncMock(side_effect=[True, False]))
    source_repository = SimpleNamespace(
        find_by_ids=AsyncMock(return_value=[SimpleNamespace(file_id=11)])
    )
    page = [
        SimpleNamespace(id=1, file_id=11, projection_version=10),
        SimpleNamespace(id=2, file_id=12, projection_version=20),
    ]

    first = await _delete_orphan_projection_page(
        projection_repository=projection_repository,
        source_repository=source_repository,
        page=page,
    )
    second = await _delete_orphan_projection_page(
        projection_repository=projection_repository,
        source_repository=source_repository,
        page=page,
    )

    assert (first, second) == (1, 0)
    assert projection_repository.delete.await_args_list[0].args == (12, 21)
    assert projection_repository.delete.await_count == 2


def test_tenant_fanout_always_uses_explicit_headers_and_knowledge_queue():
    task = MagicMock()

    _dispatch_task_for_tenants(task, [1, 5, 8], kwargs={"mode": "daily"})

    assert task.apply_async.call_count == 3
    for tenant_id, call in zip((1, 5, 8), task.apply_async.call_args_list, strict=False):
        assert call.kwargs["headers"] == {"tenant_id": tenant_id}
        assert call.kwargs["queue"] == "knowledge_celery"
        assert call.kwargs["kwargs"] == {"mode": "daily"}


def test_heat_config_fingerprint_is_canonical_and_changes_with_heat_parameters():
    first = recommendation_config_fingerprint(7, 0.3)
    same = recommendation_config_fingerprint(7, 0.30)
    changed = recommendation_config_fingerprint(8, 0.3)

    assert first == same
    assert first != changed


@pytest.mark.asyncio
async def test_interest_worker_merges_current_query_even_before_es_refresh(monkeypatch):
    build = AsyncMock(return_value=[("10:101", 3.0)])
    monkeypatch.setattr(PortalRecommendationBehaviorService, "build_interest_top50", build)
    token = current_tenant_id.set(5)
    try:
        result = await _rebuild_user_interest_async(
            user_id=7,
            current_query="safety",
            searched_at="2026-07-15T00:00:00+00:00",
        )
    finally:
        current_tenant_id.reset(token)

    assert result == 1
    assert build.await_args.kwargs["tenant_id"] == 5
    assert build.await_args.kwargs["user_id"] == 7
    assert build.await_args.kwargs["current_query"] == "safety"


def test_worker_task_imports_are_registered_explicitly():
    source = __import__("pathlib").Path(
        "src/backend/bisheng/worker/__init__.py"
    ).read_text(encoding="utf-8")

    assert "worker.knowledge.portal_recommendation" in source


@pytest.mark.asyncio
async def test_pool_count_validation_rejects_partial_version_before_cas():
    repository = SimpleNamespace(
        get_pool_size=AsyncMock(side_effect=lambda _tenant, _version, name: {"generic": 3, "generic:hot": 1}[name])
    )

    valid = await _pool_counts_match(
        repository,
        tenant_id=5,
        pool_version="9",
        expected_counts={"generic": 3, "generic:hot": 2},
    )

    assert valid is False


def test_worker_rotation_excludes_day_fifteen_through_seventeen_then_recovers_and_bounds_state():
    source = [
        PortalRecommendationCandidate(
            space_id=10,
            file_id=file_id,
            hot_score=float(1_001 - file_id),
            fresh_score=float(file_id),
        )
        for file_id in range(1, 1_001)
    ]
    start = date(2026, 7, 1)
    day1, states, _ = _assemble_rotated_pool(
        source,
        previous_states={},
        today=start,
        domain=False,
    )
    original_hot_keys = {candidate.key for candidate in day1["hot"]}
    assert len(original_hot_keys) == 500
    assert len(states) == 500

    for offset in (14, 15, 16):
        assembled, states, _ = _assemble_rotated_pool(
            source,
            previous_states=states,
            today=start + timedelta(days=offset),
            domain=False,
        )
        assert original_hot_keys.isdisjoint(
            candidate.key
            for stream in assembled.values()
            for candidate in stream
        )
        assert len(states) <= 1_000

    recovered, states, _ = _assemble_rotated_pool(
        source,
        previous_states=states,
        today=start + timedelta(days=17),
        domain=False,
    )
    assert original_hot_keys & {candidate.key for candidate in recovered["hot"]}
    assert len(states) <= 1_000
