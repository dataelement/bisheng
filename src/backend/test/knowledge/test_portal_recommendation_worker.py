# ruff: noqa: E402

import json
import sys
from contextlib import asynccontextmanager
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
    _exclude_personal_space_projections,
    _pool_counts_match,
    _projection_version_for_event,
    _rebuild_user_interest_async,
    recommendation_config_fingerprint,
)


@pytest.mark.asyncio
async def test_pool_request_reuses_context_on_retry_and_skips_completed_or_superseded(monkeypatch):
    worker = sys.modules["bisheng.worker.knowledge.portal_recommendation"]
    context = SimpleNamespace(generation=4, config_version=2, fingerprint="original")
    repository = SimpleNamespace(
        get_pool_rebuild_request=AsyncMock(return_value=context),
        get_pool_state=AsyncMock(return_value=SimpleNamespace(desired_generation=4, active_generation=3)),
    )
    rebuild = AsyncMock(side_effect=[RuntimeError("temporary failure"), True])
    config = AsyncMock()
    monkeypatch.setattr(worker, "PortalRecommendationRedisRepositoryImpl", lambda: repository)
    monkeypatch.setattr(worker, "_rebuild_shared_pools_async", rebuild)
    monkeypatch.setattr(worker.ShougangPortalConfigService, "get_config", config)
    token = current_tenant_id.set(5)
    try:
        requested_at = datetime.now(timezone.utc).timestamp()
        with pytest.raises(RuntimeError, match="temporary"):
            await worker._rebuild_pool_request_async(request_id="request-1", requested_at=requested_at)
        assert await worker._rebuild_pool_request_async(request_id="request-1", requested_at=requested_at)
        assert rebuild.await_args_list[0] == rebuild.await_args_list[1]
        assert rebuild.await_args.kwargs == {"generation": 4, "config_version": 2, "fingerprint": "original"}
        config.assert_not_awaited()
        repository.get_pool_state.return_value = SimpleNamespace(desired_generation=4, active_generation=4)
        assert await worker._rebuild_pool_request_async(request_id="request-1", requested_at=requested_at)
        repository.get_pool_state.return_value = SimpleNamespace(desired_generation=5, active_generation=4)
        assert not await worker._rebuild_pool_request_async(request_id="request-1", requested_at=requested_at)
        assert rebuild.await_count == 2
    finally:
        current_tenant_id.reset(token)


@pytest.mark.asyncio
async def test_pool_request_initializes_once_and_builds_without_republishing(monkeypatch):
    worker = sys.modules["bisheng.worker.knowledge.portal_recommendation"]
    context = SimpleNamespace(generation=1, config_version=2, fingerprint="fp")
    repository = SimpleNamespace(
        get_pool_rebuild_request=AsyncMock(return_value=None),
        get_or_create_pool_rebuild_request=AsyncMock(return_value=context),
        get_pool_state=AsyncMock(return_value=SimpleNamespace(desired_generation=1, active_generation=0)),
    )
    monkeypatch.setattr(worker, "PortalRecommendationRedisRepositoryImpl", lambda: repository)
    monkeypatch.setattr(worker.ShougangPortalConfigService, "get_config", AsyncMock(return_value=SimpleNamespace(
        version=2, portal=SimpleNamespace(recommendation=SimpleNamespace(
            hot_half_life_days=7, home_entry_source_weight=0.3,
        )),
    )))
    rebuild = AsyncMock(return_value=True)
    publish = MagicMock()
    monkeypatch.setattr(worker, "_rebuild_shared_pools_async", rebuild)
    monkeypatch.setattr(worker.rebuild_shared_pools_celery, "apply_async", publish)
    token = current_tenant_id.set(5)
    try:
        assert await worker._rebuild_pool_request_async(
            request_id="new-request", requested_at=datetime.now(timezone.utc).timestamp(),
        )
        repository.get_or_create_pool_rebuild_request.assert_awaited_once()
        rebuild.assert_awaited_once_with(generation=1, config_version=2, fingerprint="fp")
        publish.assert_not_called()
    finally:
        current_tenant_id.reset(token)


@pytest.mark.asyncio
async def test_expired_pool_request_cannot_claim_a_new_generation(monkeypatch):
    worker = sys.modules["bisheng.worker.knowledge.portal_recommendation"]
    repository_factory = MagicMock()
    monkeypatch.setattr(worker, "PortalRecommendationRedisRepositoryImpl", repository_factory)
    assert not await worker._rebuild_pool_request_async(request_id="old", requested_at=0)
    repository_factory.assert_not_called()


def test_pool_producers_publish_one_request_with_stable_identity(monkeypatch):
    worker = sys.modules["bisheng.worker.knowledge.portal_recommendation"]
    publish = MagicMock()
    monkeypatch.setattr(worker.rebuild_shared_pools_celery, "apply_async", publish)
    worker.enqueue_portal_recommendation_pool_rebuild(tenant_id=5)
    publish.assert_called_once()
    options = publish.call_args.kwargs
    assert options["headers"] == {"tenant_id": 5}
    assert options["kwargs"]["request_id"] == options["task_id"]
    assert options["kwargs"]["requested_at"] > 0


@pytest.mark.parametrize("count, sizes", [(0, []), (1, [1]), (100, [100]), (101, [100, 1])])
def test_projection_producer_publishes_bounded_batches_with_stable_delete_version(monkeypatch, count, sizes):
    worker = sys.modules["bisheng.worker.knowledge.portal_recommendation"]
    publish = MagicMock()
    monkeypatch.setattr(worker.refresh_projection_batch_celery, "apply_async", publish)
    ids = list(range(1, count + 1))
    worker.enqueue_portal_recommendation_projection_refresh_batch(
        file_ids=ids + ids, deleted=True, tenant_id=5,
    )
    batches = [call.kwargs["kwargs"]["events"] for call in publish.call_args_list]
    assert [len(batch) for batch in batches] == sizes
    events = [event for batch in batches for event in batch]
    assert [event["file_id"] for event in events] == ids
    if events:
        assert len({event["projection_version"] for event in events}) == 1
        assert all(event["deleted"] for event in events)
    assert all(call.kwargs["headers"] == {"tenant_id": 5} for call in publish.call_args_list)


def test_projection_single_update_keeps_source_version_and_event_dedup_preserves_order(monkeypatch):
    worker = sys.modules["bisheng.worker.knowledge.portal_recommendation"]
    publish = MagicMock()
    monkeypatch.setattr(worker.refresh_projection_batch_celery, "apply_async", publish)
    worker.enqueue_portal_recommendation_projection_refresh(file_id=41, tenant_id=5)
    update = {"file_id": 41, "projection_version": None, "deleted": False}
    assert publish.call_args.kwargs["kwargs"] == {"events": [update]}
    delete = {"file_id": 41, "projection_version": 100, "deleted": True}
    newer = {"file_id": 41, "projection_version": 200, "deleted": False}
    worker._publish_projection_refresh_events([update, update, delete, newer], tenant_id=5)
    assert publish.call_args.kwargs["kwargs"] == {"events": [update, delete, newer]}


def test_projection_partial_publish_failure_is_reported_without_republishing_successful_batches(monkeypatch):
    worker = sys.modules["bisheng.worker.knowledge.portal_recommendation"]
    publish = MagicMock(side_effect=[None, RuntimeError("broker unavailable")])
    monkeypatch.setattr(worker.refresh_projection_batch_celery, "apply_async", publish)
    with pytest.raises(RuntimeError, match="broker unavailable"):
        worker.enqueue_portal_recommendation_projection_refresh_batch(
            file_ids=list(range(1, 202)), deleted=False, tenant_id=5,
        )
    assert publish.call_count == 2
    assert publish.call_args_list[0].kwargs["kwargs"]["events"][0]["file_id"] == 1
    assert publish.call_args_list[1].kwargs["kwargs"]["events"][0]["file_id"] == 101


@pytest.mark.asyncio
async def test_invalid_projection_batch_is_rejected_before_opening_transaction(monkeypatch):
    worker = sys.modules["bisheng.worker.knowledge.portal_recommendation"]
    sessions = MagicMock()
    monkeypatch.setattr(worker, "get_async_db_session", sessions)
    with pytest.raises(ValueError, match="exceeds limit"):
        await worker._refresh_projection_batch_async(events=[{"file_id": 41}] * 101)
    with pytest.raises(ValueError, match="requires an event version"):
        await worker._refresh_projection_batch_async(events=[{"file_id": 41, "deleted": True}])
    sessions.assert_not_called()


@pytest.mark.asyncio
async def test_projection_batches_preserve_versions_and_rollback_only_failed_batch(monkeypatch, async_db_engine):
    from sqlmodel.ext.asyncio.session import AsyncSession

    from bisheng.knowledge.domain.repositories.implementations.portal_recommendation_repository_impl import (
        PortalRecommendationRepositoryImpl,
    )

    worker = sys.modules["bisheng.worker.knowledge.portal_recommendation"]
    source_time = datetime(2026, 7, 1, tzinfo=timezone.utc)

    async def find_by_id(file_id):
        if file_id == 44:
            raise RuntimeError("source temporarily unavailable")
        return PortalRecommendationSourceFile(
            file_id=file_id, space_id=2, file_type=1, status=2, split_rule=None,
            file_encoding=None, file_level_path=None, source_update_time=source_time,
            is_primary=True, space_level="public",
        )

    @asynccontextmanager
    async def session_factory():
        async with AsyncSession(async_db_engine, expire_on_commit=False) as session:
            yield session

    monkeypatch.setattr(worker, "get_async_db_session", session_factory)
    monkeypatch.setattr(worker, "PortalRecommendationSourceRepositoryImpl", lambda _session: SimpleNamespace(
        find_by_id=find_by_id,
    ))
    monkeypatch.setattr(PortalRecommendationProjectionService, "load_bindings_strict", AsyncMock(return_value=[]))

    def event(file_id, version=None, deleted=False):
        return {"file_id": file_id, "projection_version": version, "deleted": deleted}

    token = current_tenant_id.set(5)
    try:
        initial = [event(41, 200), event(42)]
        assert await worker._refresh_projection_batch_async(events=initial) == 2
        assert await worker._refresh_projection_batch_async(events=initial) == 0
        assert await worker._refresh_projection_batch_async(events=[event(41, 199, True)]) == 0
        with pytest.raises(RuntimeError, match="temporarily unavailable"):
            await worker._refresh_projection_batch_async(events=[event(43, 100), event(44, 100)])
        async with session_factory() as session:
            records = await PortalRecommendationRepositoryImpl(session).find_by_file_ids([41, 42, 43])
            assert {record.file_id: record.projection_version for record in records} == {
                41: 200, 42: int(source_time.timestamp() * 1_000_000),
            }
        assert await worker._refresh_projection_batch_async(events=[event(41, 300, True)]) == 1
        assert await worker._refresh_projection_batch_async(events=[event(41, 300, True)]) == 0
    finally:
        current_tenant_id.reset(token)


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
        space_level="public",
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
        assert call.kwargs["queue"] == "celery"
        assert call.kwargs["kwargs"] == {"mode": "daily"}


def test_heat_config_fingerprint_is_canonical_and_changes_with_heat_parameters():
    first = recommendation_config_fingerprint(7, 0.3)
    same = recommendation_config_fingerprint(7, 0.30)
    changed = recommendation_config_fingerprint(8, 0.3)

    assert first == same
    assert first != changed


def test_shared_pool_excludes_personal_space_projections():
    projections = [
        SimpleNamespace(file_id=1, space_id=10),
        SimpleNamespace(file_id=2, space_id=20),
        SimpleNamespace(file_id=3, space_id=30),
    ]

    filtered = _exclude_personal_space_projections(
        projections,
        personal_space_ids={20},
    )

    assert [record.file_id for record in filtered] == [1, 3]


@pytest.mark.asyncio
async def test_interest_worker_merges_current_query_even_before_es_refresh(monkeypatch):
    build = AsyncMock(return_value=[("10:101", 3.0)])
    diagnostic_payloads: list[dict] = []

    def capture_log(message, payload):
        if message == "[diag][portal.recommendation.interest_refresh] {}":
            diagnostic_payloads.append(json.loads(payload))

    monkeypatch.setattr(PortalRecommendationBehaviorService, "build_interest_top50", build)
    worker_module = sys.modules["bisheng.worker.knowledge.portal_recommendation"]
    monkeypatch.setattr(worker_module.logger, "info", capture_log)
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
    assert diagnostic_payloads[0]["current_query_present"] is True
    assert diagnostic_payloads[0]["interest_count"] == 1
    assert diagnostic_payloads[0]["tenant_id"] == 5
    assert diagnostic_payloads[0]["user_id"] == 7
    assert "safety" not in json.dumps(diagnostic_payloads[0])


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
