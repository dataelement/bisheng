"""Tenant-aware Celery maintenance for Shougang portal recommendations."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any

from bisheng.core.context.tenant import DEFAULT_TENANT_ID, get_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.database.models.department import UserDepartmentDao
from bisheng.database.models.tenant import TenantDao
from bisheng.knowledge.domain.repositories.implementations.portal_recommendation_redis_repository import (
    PortalRecommendationRedisRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.portal_recommendation_repository_impl import (
    PortalRecommendationRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.portal_recommendation_source_repository_impl import (
    PortalRecommendationSourceRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.portal_recommendation_telemetry_repository_impl import (
    PortalRecommendationTelemetryRepositoryImpl,
)
from bisheng.knowledge.domain.services.portal_recommendation_behavior_service import (
    PortalRecommendationBehaviorService,
)
from bisheng.knowledge.domain.services.portal_recommendation_pool_service import (
    PortalRecommendationPoolService,
    PortalRecommendationPoolState,
)
from bisheng.knowledge.domain.services.portal_recommendation_projection_service import (
    PortalRecommendationProjectionService,
    PortalRecommendationSourceFile,
)
from bisheng.knowledge.domain.services.portal_recommendation_service import PortalRecommendationCandidate
from bisheng.shougang_portal_config.domain.services.portal_config_service import ShougangPortalConfigService
from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.main import bisheng_celery

KNOWLEDGE_QUEUE = "knowledge_celery"
PROJECTION_PAGE_SIZE = 500


def recommendation_config_fingerprint(half_life_days: int, source_weight: float) -> str:
    canonical = json.dumps(
        {
            "home_entry_source_weight": float(source_weight),
            "hot_half_life_days": int(half_life_days),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _dispatch_task_for_tenants(task, tenant_ids: list[int], *, kwargs: dict | None = None) -> None:
    for tenant_id in sorted({int(value) for value in tenant_ids if int(value) > 0}):
        task.apply_async(
            kwargs=dict(kwargs or {}),
            headers={"tenant_id": tenant_id},
            queue=KNOWLEDGE_QUEUE,
        )


def enqueue_portal_recommendation_projection_refresh(
    *,
    file_id: int,
    projection_version: int | None = None,
    deleted: bool = False,
    tenant_id: int | None = None,
) -> None:
    resolved_tenant_id = int(tenant_id or get_current_tenant_id() or DEFAULT_TENANT_ID)
    if deleted and projection_version is None:
        projection_version = int(datetime.now(timezone.utc).timestamp() * 1_000_000)
    refresh_projection_celery.apply_async(
        kwargs={
            "file_id": int(file_id),
            "projection_version": projection_version,
            "deleted": bool(deleted),
        },
        headers={"tenant_id": resolved_tenant_id},
        queue=KNOWLEDGE_QUEUE,
    )


def enqueue_portal_recommendation_projection_refresh_batch(
    *,
    file_ids: list[int],
    deleted: bool,
    tenant_id: int | None = None,
) -> None:
    normalized_ids = sorted({int(value) for value in file_ids})
    if not normalized_ids:
        return
    resolved_tenant_id = int(tenant_id or get_current_tenant_id() or DEFAULT_TENANT_ID)
    projection_version = int(datetime.now(timezone.utc).timestamp() * 1_000_000)
    refresh_projection_batch_celery.apply_async(
        kwargs={
            "file_ids": normalized_ids,
            "projection_version": projection_version,
            "deleted": bool(deleted),
        },
        headers={"tenant_id": resolved_tenant_id},
        queue=KNOWLEDGE_QUEUE,
    )


def enqueue_portal_recommendation_resource_refresh(
    *,
    resource_type: str,
    resource_id: int,
    tenant_id: int | None = None,
) -> None:
    resolved_tenant_id = int(tenant_id or get_current_tenant_id() or DEFAULT_TENANT_ID)
    event_version = int(datetime.now(timezone.utc).timestamp() * 1_000_000)
    refresh_projection_resource_celery.apply_async(
        kwargs={
            "resource_type": str(resource_type),
            "resource_id": int(resource_id),
            "event_version": event_version,
        },
        headers={"tenant_id": resolved_tenant_id},
        queue=KNOWLEDGE_QUEUE,
    )


def enqueue_portal_recommendation_user_invalidation(
    *,
    user_ids: list[int],
    tenant_id: int | None = None,
) -> None:
    normalized_ids = sorted({int(value) for value in user_ids})
    if not normalized_ids:
        return
    resolved_tenant_id = int(tenant_id or get_current_tenant_id() or DEFAULT_TENANT_ID)
    invalidate_user_ids_celery.apply_async(
        kwargs={"user_ids": normalized_ids},
        headers={"tenant_id": resolved_tenant_id},
        queue=KNOWLEDGE_QUEUE,
    )


def enqueue_portal_recommendation_config_post_commit(
    *,
    tenant_id: int,
    department_ids: list[int],
    rebuild_pools: bool,
) -> None:
    headers = {"tenant_id": int(tenant_id)}
    if department_ids:
        invalidate_department_users_celery.apply_async(
            kwargs={"department_ids": sorted({int(value) for value in department_ids})},
            headers=headers,
            queue=KNOWLEDGE_QUEUE,
        )
    if rebuild_pools:
        prepare_pool_rebuild_celery.apply_async(
            headers=headers,
            queue=KNOWLEDGE_QUEUE,
        )


def enqueue_portal_recommendation_pool_rebuild(*, tenant_id: int | None = None) -> None:
    resolved_tenant_id = int(tenant_id or get_current_tenant_id() or DEFAULT_TENANT_ID)
    prepare_pool_rebuild_celery.apply_async(
        headers={"tenant_id": resolved_tenant_id},
        queue=KNOWLEDGE_QUEUE,
    )


async def _refresh_projection_async(
    *,
    file_id: int,
    projection_version: int | None,
    deleted: bool,
) -> bool:
    async with get_async_db_session() as session:
        service = PortalRecommendationProjectionService(
            source_repository=PortalRecommendationSourceRepositoryImpl(session),
            projection_repository=PortalRecommendationRepositoryImpl(session),
        )
        async with session.begin():
            return await service.refresh_file(
                int(file_id),
                projection_version=projection_version,
                deleted=deleted,
            )


@bisheng_celery.task(
    bind=True,
    name="bisheng.worker.knowledge.portal_recommendation.refresh_portal_recommendation_projection",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 5},
    acks_late=True,
)
def refresh_projection_celery(
    _task,
    file_id: int,
    projection_version: int | None = None,
    deleted: bool = False,
):
    return run_async_task(
        lambda: _refresh_projection_async(
            file_id=file_id,
            projection_version=projection_version,
            deleted=deleted,
        )
    )


async def _refresh_projection_batch_async(
    *,
    file_ids: list[int],
    projection_version: int,
    deleted: bool,
) -> int:
    changed = 0
    async with get_async_db_session() as session:
        service = PortalRecommendationProjectionService(
            source_repository=PortalRecommendationSourceRepositoryImpl(session),
            projection_repository=PortalRecommendationRepositoryImpl(session),
        )
        async with session.begin():
            for file_id in sorted({int(value) for value in file_ids}):
                changed += int(
                    await service.refresh_file(
                        file_id,
                        projection_version=projection_version,
                        deleted=deleted,
                    )
                )
    return changed


@bisheng_celery.task(
    bind=True,
    name="bisheng.worker.knowledge.portal_recommendation.refresh_portal_recommendation_projection_batch",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 5},
    acks_late=True,
)
def refresh_projection_batch_celery(
    _task,
    file_ids: list[int],
    projection_version: int,
    deleted: bool = False,
):
    return run_async_task(
        lambda: _refresh_projection_batch_async(
            file_ids=file_ids,
            projection_version=projection_version,
            deleted=deleted,
        )
    )


def _projection_version_for_event(
    service: PortalRecommendationProjectionService,
    source: PortalRecommendationSourceFile,
    event_version: int,
) -> int:
    return max(service.projection_version_for(source), int(event_version))


async def _refresh_projection_resource_async(
    *,
    resource_type: str,
    resource_id: int,
    event_version: int,
) -> int:
    processed = 0
    after_id = 0
    while True:
        async with get_async_db_session() as session:
            source_repository = PortalRecommendationSourceRepositoryImpl(session)
            service = PortalRecommendationProjectionService(
                source_repository=source_repository,
                projection_repository=PortalRecommendationRepositoryImpl(session),
            )
            async with session.begin():
                page = await source_repository.list_for_resource(
                    resource_type,
                    resource_id,
                    after_id=after_id,
                    limit=PROJECTION_PAGE_SIZE,
                )
                for source in page:
                    processed += int(
                        await service.refresh_file(
                            source.file_id,
                            projection_version=_projection_version_for_event(
                                service,
                                source,
                                event_version,
                            ),
                        )
                    )
            if not page:
                return processed
            after_id = page[-1].file_id


@bisheng_celery.task(
    bind=True,
    name="bisheng.worker.knowledge.portal_recommendation.refresh_portal_recommendation_projection_resource",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 5},
    acks_late=True,
)
def refresh_projection_resource_celery(
    _task,
    resource_type: str,
    resource_id: int,
    event_version: int,
):
    return run_async_task(
        lambda: _refresh_projection_resource_async(
            resource_type=resource_type,
            resource_id=resource_id,
            event_version=event_version,
        )
    )


async def _rebuild_user_interest_async(
    *,
    user_id: int,
    current_query: str | None,
    searched_at: str | datetime | None,
) -> int:
    tenant_id = int(get_current_tenant_id() or DEFAULT_TENANT_ID)
    if isinstance(searched_at, str):
        searched_at = datetime.fromisoformat(searched_at)
    service = PortalRecommendationBehaviorService(
        state_repository=PortalRecommendationRedisRepositoryImpl(),
        telemetry_repository=PortalRecommendationTelemetryRepositoryImpl(),
    )
    entries = await service.build_interest_top50(
        tenant_id=tenant_id,
        user_id=int(user_id),
        current_query=current_query,
        searched_at=searched_at,
    )
    return len(entries)


@bisheng_celery.task(
    bind=True,
    name="bisheng.worker.knowledge.portal_recommendation.rebuild_user_interest_top50",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 5},
    acks_late=True,
)
def rebuild_user_interest_celery(
    _task,
    user_id: int,
    current_query: str | None = None,
    searched_at: str | None = None,
):
    return run_async_task(
        lambda: _rebuild_user_interest_async(
            user_id=user_id,
            current_query=current_query,
            searched_at=searched_at,
        )
    )


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(math.ceil(len(ordered) * 0.95) - 1, 0)]


async def _load_all_projections(repository: PortalRecommendationRepositoryImpl) -> list[Any]:
    result = []
    after_id = 0
    while True:
        page = await repository.list_page(after_id=after_id, limit=PROJECTION_PAGE_SIZE)
        if not page:
            return result
        result.extend(page)
        after_id = page[-1].id


def _candidate_from_projection(record, *, hot_score: float, now: datetime) -> PortalRecommendationCandidate:
    updated_at = record.source_update_time
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    age_days = max((now - updated_at).total_seconds(), 0) / 86400
    return PortalRecommendationCandidate(
        space_id=int(record.space_id),
        file_id=int(record.file_id),
        hot_score=hot_score,
        fresh_score=100 * math.pow(2, -age_days / 45),
        is_public=False,
        normal_acl=False,
        eligible=bool(record.recommendable),
    )


def _assemble_rotated_pool(
    source: list[PortalRecommendationCandidate],
    *,
    previous_states,
    today,
    domain: bool,
) -> tuple[
    dict[str, list[PortalRecommendationCandidate]],
    dict[tuple[int, int], Any],
    int,
]:
    hot = sorted(source, key=lambda item: (-item.hot_score, -item.file_id))
    fresh = sorted(source, key=lambda item: (-item.fresh_score, -item.file_id))
    rotated_hot, advanced_states, filtered_count = PortalRecommendationPoolService.rotate_hot_candidates(
        hot,
        states=previous_states,
        today=today,
    )
    cooldown_keys = {
        key
        for key, state in advanced_states.items()
        if not PortalRecommendationPoolService.is_rotation_active(state, today)
    }
    fresh = [candidate for candidate in fresh if candidate.key not in cooldown_keys]
    hot_entries = rotated_hot[:500]
    merged = PortalRecommendationPoolService.interleave_hot_fresh(rotated_hot, fresh, limit=500)
    next_states = {key: advanced_states[key] for key in cooldown_keys}
    for candidate in hot_entries:
        next_states[candidate.key] = advanced_states.get(
            candidate.key,
            PortalRecommendationPoolState(active_since=today),
        )
    if domain:
        merged = [replace(candidate, domain_score=100.0) for candidate in merged]
        hot_entries = [replace(candidate, domain_score=100.0) for candidate in hot_entries]
        fresh = [replace(candidate, domain_score=100.0) for candidate in fresh[:500]]
    else:
        fresh = fresh[:500]
    return {"merged": merged, "hot": hot_entries, "fresh": fresh}, next_states, filtered_count


async def _pool_counts_match(
    repository: PortalRecommendationRedisRepositoryImpl,
    *,
    tenant_id: int,
    pool_version: str,
    expected_counts: dict[str, int],
) -> bool:
    for pool_name, expected_count in expected_counts.items():
        if await repository.get_pool_size(tenant_id, pool_version, pool_name) != expected_count:
            return False
    return True


async def _rebuild_shared_pools_async(
    *,
    generation: int,
    config_version: int,
    fingerprint: str,
) -> bool:
    tenant_id = int(get_current_tenant_id() or DEFAULT_TENANT_ID)
    config = await ShougangPortalConfigService.get_config(tenant_id=tenant_id)
    if config is None or int(config.version) != int(config_version):
        return False
    recommendation = config.portal.recommendation
    current_fingerprint = recommendation_config_fingerprint(
        recommendation.hot_half_life_days,
        recommendation.home_entry_source_weight,
    )
    if current_fingerprint != fingerprint:
        return False

    async with get_async_db_session() as session:
        projections = [
            record
            for record in await _load_all_projections(PortalRecommendationRepositoryImpl(session))
            if record.recommendable
        ]
    telemetry = PortalRecommendationTelemetryRepositoryImpl()
    now = datetime.now(timezone.utc)
    views = await telemetry.list_recent_document_views(
        tenant_id,
        now - timedelta(days=30),
        now,
        None,
    )
    views_by_file: dict[int, list] = defaultdict(list)
    for view in views:
        views_by_file[int(view.file_id)].append(view)
    decayed = {
        int(record.file_id): PortalRecommendationPoolService.decayed_view_count(
            views_by_file.get(int(record.file_id), []),
            now=now,
            half_life_days=float(recommendation.hot_half_life_days),
            recommendation_source_weight=float(recommendation.home_entry_source_weight),
        )
        for record in projections
    }
    p95 = _p95(list(decayed.values()))

    candidates: list[PortalRecommendationCandidate] = []
    record_by_key = {}
    for record in projections:
        count = decayed[int(record.file_id)]
        hot_score = 0.0 if p95 <= 0 else min(math.log1p(count) / math.log1p(p95), 1.0) * 100
        candidate = _candidate_from_projection(record, hot_score=hot_score, now=now)
        candidates.append(candidate)
        record_by_key[candidate.key] = record

    redis_repository = PortalRecommendationRedisRepositoryImpl()
    pool_version = str(int(generation))
    previous_pool_state = await redis_repository.get_pool_state(tenant_id)
    previous_pool_version = previous_pool_state.active_pool_version or ""
    built_counts: dict[str, int] = {}
    projection_samples: set[tuple[int, int]] = set()

    async def write_pool(name: str, source: list[PortalRecommendationCandidate], *, domain: bool) -> None:
        previous_states = await redis_repository.get_hot_rotation_states(
            tenant_id,
            previous_pool_version,
            name,
        )
        assembled, next_states, _filtered_count = _assemble_rotated_pool(
            source,
            previous_states=previous_states,
            today=PortalRecommendationPoolService.business_date(now),
            domain=domain,
        )
        merged = assembled["merged"]
        streams = {
            name: merged,
            f"{name}:hot": assembled["hot"],
            f"{name}:fresh": assembled["fresh"],
        }
        for pool_name, entries in streams.items():
            await redis_repository.replace_pool(
                tenant_id,
                pool_version,
                pool_name,
                [(candidate, float(500 - index)) for index, candidate in enumerate(entries)],
            )
            built_counts[pool_name] = len(entries)
        await redis_repository.replace_hot_rotation_states(
            tenant_id,
            pool_version,
            name,
            next_states,
        )
        for candidate in merged[:3]:
            projection_samples.add(candidate.key)

    await write_pool("generic", candidates, domain=False)
    domain_codes = sorted(
        {
            str(record.business_domain_code)
            for record in projections
            if record.business_domain_code
        }
    )
    for domain_code in domain_codes:
        await write_pool(
            f"domain:{domain_code}",
            [
                candidate
                for candidate in candidates
                if record_by_key[candidate.key].business_domain_code == domain_code
            ],
            domain=True,
        )

    latest = await ShougangPortalConfigService.get_config(tenant_id=tenant_id)
    if latest is None or int(latest.version) != int(config_version):
        return False
    latest_fingerprint = recommendation_config_fingerprint(
        latest.portal.recommendation.hot_half_life_days,
        latest.portal.recommendation.home_entry_source_weight,
    )
    if latest_fingerprint != fingerprint:
        return False
    if not await _pool_counts_match(
        redis_repository,
        tenant_id=tenant_id,
        pool_version=pool_version,
        expected_counts=built_counts,
    ):
        return False
    if projection_samples:
        async with get_async_db_session() as session:
            sample_records = await PortalRecommendationRepositoryImpl(session).find_by_file_ids(
                [file_id for _space_id, file_id in projection_samples]
            )
        sample_map = {(record.space_id, record.file_id): record for record in sample_records}
        if any(
            key not in sample_map
            or not sample_map[key].recommendable
            or int(sample_map[key].tenant_id) != tenant_id
            for key in projection_samples
        ):
            return False
    latest_pool_state = await redis_repository.get_pool_state(tenant_id)
    if (
        int(latest_pool_state.desired_generation) != int(generation)
        or int(latest_pool_state.active_generation) >= int(generation)
    ):
        return False
    await redis_repository.mark_pool_version_ready(tenant_id, pool_version)
    return await redis_repository.activate_pool_if_current(
        tenant_id,
        int(generation),
        pool_version,
        fingerprint,
    )


@bisheng_celery.task(
    bind=True,
    name="bisheng.worker.knowledge.portal_recommendation.rebuild_portal_recommendation_pools",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
    time_limit=1800,
    acks_late=True,
)
def rebuild_shared_pools_celery(
    _task,
    generation: int,
    config_version: int,
    fingerprint: str,
):
    return run_async_task(
        lambda: _rebuild_shared_pools_async(
            generation=generation,
            config_version=config_version,
            fingerprint=fingerprint,
        )
    )


async def _prepare_pool_rebuild_async() -> bool:
    tenant_id = int(get_current_tenant_id() or DEFAULT_TENANT_ID)
    config = await ShougangPortalConfigService.get_config(tenant_id=tenant_id)
    if config is None:
        return False
    recommendation = config.portal.recommendation
    redis_repository = PortalRecommendationRedisRepositoryImpl()
    generation = await redis_repository.increment_desired_generation(tenant_id)
    fingerprint = recommendation_config_fingerprint(
        recommendation.hot_half_life_days,
        recommendation.home_entry_source_weight,
    )
    rebuild_shared_pools_celery.apply_async(
        kwargs={
            "generation": generation,
            "config_version": int(config.version),
            "fingerprint": fingerprint,
        },
        headers={"tenant_id": tenant_id},
        queue=KNOWLEDGE_QUEUE,
    )
    return True


@bisheng_celery.task(name="bisheng.worker.knowledge.portal_recommendation.prepare_pool_rebuild")
def prepare_pool_rebuild_celery():
    return run_async_task(_prepare_pool_rebuild_async)


async def _reconcile_incremental_async() -> int:
    tenant_id = int(get_current_tenant_id() or DEFAULT_TENANT_ID)
    redis_repository = PortalRecommendationRedisRepositoryImpl()
    watermark = await redis_repository.get_reconcile_watermark(tenant_id)
    update_time, file_id = watermark or (datetime(1970, 1, 1, tzinfo=timezone.utc), 0)
    processed = 0
    while True:
        async with get_async_db_session() as session:
            source_repository = PortalRecommendationSourceRepositoryImpl(session)
            projection_service = PortalRecommendationProjectionService(
                source_repository=source_repository,
                projection_repository=PortalRecommendationRepositoryImpl(session),
            )
            async with session.begin():
                page = await source_repository.list_changed_after(
                    update_time=update_time,
                    file_id=file_id,
                    limit=PROJECTION_PAGE_SIZE,
                )
                for source in page:
                    await projection_service.refresh_file(
                        source.file_id,
                        projection_version=projection_service.projection_version_for(source),
                    )
            if not page:
                return processed
            update_time, file_id = page[-1].source_update_time, page[-1].file_id
        await redis_repository.set_reconcile_watermark(tenant_id, update_time, file_id)
        processed += len(page)


@bisheng_celery.task(
    bind=True,
    name="bisheng.worker.knowledge.portal_recommendation.reconcile_portal_recommendation_incremental",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
    acks_late=True,
)
def reconcile_incremental_celery(_task):
    return run_async_task(_reconcile_incremental_async)


async def _delete_orphan_projection_page(
    *,
    projection_repository,
    source_repository,
    page,
) -> int:
    present_ids = {
        source.file_id
        for source in await source_repository.find_by_ids([record.file_id for record in page])
    }
    deleted = 0
    for record in page:
        if record.file_id in present_ids:
            continue
        deleted += int(
            await projection_repository.delete(
                record.file_id,
                int(record.projection_version) + 1,
            )
        )
    return deleted


async def _reconcile_full_async() -> int:
    processed = 0
    after_id = 0
    reconcile_version = int(datetime.now(timezone.utc).timestamp() * 1_000_000)
    while True:
        async with get_async_db_session() as session:
            source_repository = PortalRecommendationSourceRepositoryImpl(session)
            projection_service = PortalRecommendationProjectionService(
                source_repository=source_repository,
                projection_repository=PortalRecommendationRepositoryImpl(session),
            )
            async with session.begin():
                page = await source_repository.list_page(after_id=after_id, limit=PROJECTION_PAGE_SIZE)
                for source in page:
                    await projection_service.refresh_file(
                        source.file_id,
                        projection_version=_projection_version_for_event(
                            projection_service,
                            source,
                            reconcile_version,
                        ),
                    )
            if not page:
                break
            after_id = page[-1].file_id
            processed += len(page)

    orphan_after_id = 0
    while True:
        async with get_async_db_session() as session:
            source_repository = PortalRecommendationSourceRepositoryImpl(session)
            projection_repository = PortalRecommendationRepositoryImpl(session)
            async with session.begin():
                page = await projection_repository.list_page(
                    after_id=orphan_after_id,
                    limit=PROJECTION_PAGE_SIZE,
                )
                if page:
                    processed += await _delete_orphan_projection_page(
                        projection_repository=projection_repository,
                        source_repository=source_repository,
                        page=page,
                    )
            if not page:
                return processed
            orphan_after_id = page[-1].id


@bisheng_celery.task(
    bind=True,
    name="bisheng.worker.knowledge.portal_recommendation.reconcile_portal_recommendation_full",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
    time_limit=3600,
    acks_late=True,
)
def reconcile_full_celery(_task):
    return run_async_task(_reconcile_full_async)


async def _purge_expired_searches_async() -> int:
    tenant_id = int(get_current_tenant_id() or DEFAULT_TENANT_ID)
    return await PortalRecommendationTelemetryRepositoryImpl().delete_expired_searches(
        tenant_id,
        datetime.now(timezone.utc) - timedelta(days=90),
    )


@bisheng_celery.task(
    bind=True,
    name="bisheng.worker.knowledge.portal_recommendation.purge_expired_portal_search_events",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 5},
    acks_late=True,
)
def purge_expired_searches_celery(_task):
    return run_async_task(_purge_expired_searches_async)


async def _invalidate_department_users_async(department_ids: list[int]) -> int:
    tenant_id = int(get_current_tenant_id() or DEFAULT_TENANT_ID)
    user_ids: set[int] = set()
    for department_id in sorted({int(value) for value in department_ids}):
        user_ids.update(
            await UserDepartmentDao.aget_user_ids_by_department(
                department_id,
                is_primary=True,
            )
        )
    return await _invalidate_user_ids_async(sorted(user_ids), tenant_id=tenant_id)


async def _invalidate_user_ids_async(
    user_ids: list[int],
    *,
    tenant_id: int | None = None,
) -> int:
    resolved_tenant_id = int(tenant_id or get_current_tenant_id() or DEFAULT_TENANT_ID)
    repository = PortalRecommendationRedisRepositoryImpl()
    normalized_ids = sorted({int(value) for value in user_ids})
    for user_id in normalized_ids:
        await repository.invalidate_user(resolved_tenant_id, user_id)
    return len(normalized_ids)


@bisheng_celery.task(
    bind=True,
    name="bisheng.worker.knowledge.portal_recommendation.invalidate_portal_recommendation_user_state",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
    acks_late=True,
)
def invalidate_department_users_celery(_task, department_ids: list[int]):
    return run_async_task(lambda: _invalidate_department_users_async(department_ids))


@bisheng_celery.task(
    bind=True,
    name="bisheng.worker.knowledge.portal_recommendation.invalidate_portal_recommendation_users",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
    acks_late=True,
)
def invalidate_user_ids_celery(_task, user_ids: list[int]):
    return run_async_task(lambda: _invalidate_user_ids_async(user_ids))


_MAINTENANCE_TASKS = {
    "pools": prepare_pool_rebuild_celery,
    "incremental": reconcile_incremental_celery,
    "full": reconcile_full_celery,
    "purge": purge_expired_searches_celery,
}


async def _fanout_maintenance_async(kind: str) -> int:
    task = _MAINTENANCE_TASKS.get(kind)
    if task is None:
        raise ValueError("unknown portal recommendation maintenance kind")
    tenant_ids = [DEFAULT_TENANT_ID, *(await TenantDao.aget_children_ids_active(DEFAULT_TENANT_ID))]
    _dispatch_task_for_tenants(task, tenant_ids)
    return len(set(tenant_ids))


@bisheng_celery.task(
    name="bisheng.worker.knowledge.portal_recommendation.fanout_portal_recommendation_maintenance"
)
def fanout_portal_recommendation_maintenance(kind: str):
    return run_async_task(lambda: _fanout_maintenance_async(kind))
