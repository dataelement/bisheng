"""Tenant-aware Celery maintenance for Shougang portal recommendations."""

from __future__ import annotations

import hashlib
import heapq
import json
import math
import time
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryFile
from typing import Any
from uuid import uuid4

from loguru import logger

from bisheng.core.context.tenant import DEFAULT_TENANT_ID, get_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.database.models.tenant import TenantDao
from bisheng.knowledge.domain.models.knowledge_space_scope import (
    KnowledgeSpaceLevelEnum,
    KnowledgeSpaceScopeDao,
)
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
from bisheng.knowledge.domain.repositories.interfaces.portal_recommendation_repository import (
    PortalRecommendationProjectionDelete,
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

DEFAULT_QUEUE = "celery"
PROJECTION_PAGE_SIZE = 500
PROJECTION_BATCH_SIZE = 100
POOL_REQUEST_RETENTION_SECONDS = 7 * 86400


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
            queue=DEFAULT_QUEUE,
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
    _publish_projection_refresh_events(
        [{
            "file_id": int(file_id),
            "projection_version": projection_version,
            "deleted": bool(deleted),
        }],
        tenant_id=resolved_tenant_id,
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
    _publish_projection_refresh_events(
        [{
            "file_id": file_id,
            "projection_version": projection_version,
            "deleted": bool(deleted),
        } for file_id in normalized_ids],
        tenant_id=resolved_tenant_id,
    )


def _normalize_projection_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = []
    seen = set()
    for event in events:
        file_id = event["file_id"]
        version = event.get("projection_version")
        deleted = event.get("deleted", False)
        if type(file_id) is not int or file_id <= 0 or type(deleted) is not bool:
            raise ValueError("invalid projection refresh event")
        if version is not None and (type(version) is not int or version < 0):
            raise ValueError("invalid projection event version")
        if deleted and version is None:
            raise ValueError("projection delete requires an event version")
        key = (file_id, version, deleted)
        if key in seen:
            continue
        seen.add(key)
        normalized.append({"file_id": file_id, "projection_version": version, "deleted": deleted})
    return normalized


def _publish_projection_refresh_events(events: list[dict[str, Any]], *, tenant_id: int) -> None:
    normalized = _normalize_projection_events(events)
    for offset in range(0, len(normalized), PROJECTION_BATCH_SIZE):
        batch = normalized[offset:offset + PROJECTION_BATCH_SIZE]
        try:
            refresh_projection_batch_celery.apply_async(
                kwargs={"events": batch},
                headers={"tenant_id": int(tenant_id)},
                queue=DEFAULT_QUEUE,
            )
        except Exception:
            logger.exception(
                "recommendation batch publish failed tenant_id={} offset={} batch_size={} total={}",
                tenant_id, offset, len(batch), len(normalized),
            )
            raise


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
        queue=DEFAULT_QUEUE,
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
        queue=DEFAULT_QUEUE,
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
            queue=DEFAULT_QUEUE,
        )
    if rebuild_pools:
        enqueue_portal_recommendation_pool_rebuild(tenant_id=tenant_id)


def enqueue_portal_recommendation_pool_rebuild(*, tenant_id: int | None = None) -> None:
    resolved_tenant_id = int(tenant_id or get_current_tenant_id() or DEFAULT_TENANT_ID)
    request_id = uuid4().hex
    rebuild_shared_pools_celery.apply_async(
        kwargs={"request_id": request_id, "requested_at": time.time()},
        task_id=request_id,
        headers={"tenant_id": resolved_tenant_id},
        queue=DEFAULT_QUEUE,
    )


async def _refresh_projection_batch_async(
    *,
    events: list[dict[str, Any]],
) -> int:
    if len(events) > PROJECTION_BATCH_SIZE:
        raise ValueError("projection refresh batch exceeds limit")
    normalized = _normalize_projection_events(events)
    if not normalized:
        return 0
    changed = 0
    async with get_async_db_session() as session:
        service = PortalRecommendationProjectionService(
            source_repository=PortalRecommendationSourceRepositoryImpl(session),
            projection_repository=PortalRecommendationRepositoryImpl(session),
        )
        async with session.begin():
            changed = await service.refresh_batch(normalized)
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
    events: list[dict[str, Any]],
):
    return run_async_task(
        lambda: _refresh_projection_batch_async(events=events)
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
                processed += await service.refresh_batch([
                    {"file_id": source.file_id,
                     "projection_version": _projection_version_for_event(service, source, event_version)}
                    for source in page
                ], sources=page)
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
    started_at = time.monotonic()
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
    logger.info(
        "[diag][portal.recommendation.interest_refresh] {}",
        json.dumps(
            {
                "current_query_present": bool((current_query or "").strip()),
                "duration_ms": round((time.monotonic() - started_at) * 1000, 2),
                "interest_count": len(entries),
                "searched_at_present": searched_at is not None,
                "status": "success",
                "tenant_id": tenant_id,
                "user_id": int(user_id),
            },
            sort_keys=True,
        ),
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


async def _projection_pages(repository: PortalRecommendationRepositoryImpl):
    after_id = 0
    while True:
        page = await repository.list_page(after_id=after_id, limit=PROJECTION_PAGE_SIZE)
        if not page:
            return
        yield page
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


def _exclude_personal_space_projections(
    projections: list[Any],
    personal_space_ids: set[int],
) -> list[Any]:
    return [
        record
        for record in projections
        if int(record.space_id) not in personal_space_ids
    ]


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


class _BoundedPoolCandidates:
    """每个池只保留热度和新鲜度前 500 项, 冷却状态单独保留。"""

    def __init__(self, previous_states, *, today):
        self.previous_states = previous_states
        self.today = today
        self.hot = []
        self.fresh = []
        self.cooldown_states = {}

    @staticmethod
    def _offer(heap, candidate, score):
        value = (score, candidate.file_id, candidate)
        if len(heap) < 500:
            heapq.heappush(heap, value)
        elif value[:2] > heap[0][:2]:
            heapq.heapreplace(heap, value)

    def add(self, candidate):
        previous = self.previous_states.get(candidate.key)
        if previous is not None:
            state = PortalRecommendationPoolService.advance_rotation(previous, self.today)
            if not PortalRecommendationPoolService.is_rotation_active(state, self.today):
                self.cooldown_states[candidate.key] = state
                return
        self._offer(self.hot, candidate, candidate.hot_score)
        self._offer(self.fresh, candidate, candidate.fresh_score)

    def finish(self, *, domain):
        candidates = {item[2].key: item[2] for item in [*self.hot, *self.fresh]}
        assembled, states, _ = _assemble_rotated_pool(
            list(candidates.values()), previous_states=self.previous_states, today=self.today, domain=domain,
        )
        return assembled, {**self.cooldown_states, **states}


async def _prepare_pool_candidates(
    *, redis_repository, tenant_id, previous_pool_version, now, personal_space_ids, decayed,
):
    pools = {}

    async def pool(name):
        if name not in pools:
            states = await redis_repository.get_hot_rotation_states(tenant_id, previous_pool_version, name)
            pools[name] = _BoundedPoolCandidates(states, today=PortalRecommendationPoolService.business_date(now))
        return pools[name]

    await pool("generic")
    heat_values = []
    excluded = 0
    # 保存轻量快照到临时文件, 避免全部 ORM 投影及候选常驻内存, 也避免两遍查库读到不同版本。
    with TemporaryFile(mode="w+t", encoding="utf-8") as snapshot:
        async with get_async_db_session() as session:
            async for page in _projection_pages(PortalRecommendationRepositoryImpl(session)):
                for record in page:
                    if not record.recommendable:
                        continue
                    if int(record.space_id) in personal_space_ids:
                        excluded += 1
                        continue
                    heat = decayed.get(int(record.file_id), 0.0)
                    heat_values.append(heat)
                    candidate = _candidate_from_projection(record, hot_score=0, now=now)
                    snapshot.write(json.dumps([
                        candidate.space_id, candidate.file_id, candidate.fresh_score,
                        record.business_domain_code, heat,
                    ]) + "\n")
        count = len(heat_values)
        p95 = _p95(heat_values)
        del heat_values
        snapshot.seek(0)
        for line in snapshot:
            space_id, file_id, fresh_score, domain, heat = json.loads(line)
            candidate = PortalRecommendationCandidate(
                space_id=space_id, file_id=file_id, fresh_score=fresh_score,
                hot_score=0.0 if p95 <= 0 else min(math.log1p(heat) / math.log1p(p95), 1.0) * 100,
                is_public=False, normal_acl=False, eligible=True,
            )
            pools["generic"].add(candidate)
            if domain:
                (await pool(f"domain:{domain}")).add(candidate)
    return pools, count, excluded


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
    started_at = time.monotonic()
    tenant_id = int(get_current_tenant_id() or DEFAULT_TENANT_ID)

    def log_result(status: str, reason: str, **details: Any) -> None:
        logger.info(
            "[diag][portal.recommendation.pool_refresh] {}",
            json.dumps(
                {
                    "config_version": int(config_version),
                    "duration_ms": round((time.monotonic() - started_at) * 1000, 2),
                    "generation": int(generation),
                    "reason": reason,
                    "status": status,
                    "tenant_id": tenant_id,
                    **details,
                },
                sort_keys=True,
            ),
        )

    config = await ShougangPortalConfigService.get_config(tenant_id=tenant_id)
    if config is None:
        log_result("skipped", "config_missing")
        return False
    if int(config.version) != int(config_version):
        log_result("skipped", "config_version_changed", actual_config_version=int(config.version))
        return False
    recommendation = config.portal.recommendation
    current_fingerprint = recommendation_config_fingerprint(
        recommendation.hot_half_life_days,
        recommendation.home_entry_source_weight,
    )
    if current_fingerprint != fingerprint:
        log_result("skipped", "config_fingerprint_changed")
        return False

    personal_space_ids = {
        int(space_id)
        for space_id in await KnowledgeSpaceScopeDao.aget_space_ids_by_level(
            KnowledgeSpaceLevelEnum.PERSONAL
        )
    }
    telemetry = PortalRecommendationTelemetryRepositoryImpl()
    now = datetime.now(timezone.utc)
    views = await telemetry.list_recent_document_views(
        tenant_id,
        now - timedelta(days=30),
        now,
        None,
    )
    recent_view_count = len(views)
    decayed: dict[int, float] = defaultdict(float)
    # 仓储已经按用户、文件、业务日去重; 直接累计, 避免再次建立全量分组列表。
    for view in views:
        decayed[int(view.file_id)] += PortalRecommendationPoolService.decayed_view_count(
            [view],
            now=now,
            half_life_days=float(recommendation.hot_half_life_days),
            recommendation_source_weight=float(recommendation.home_entry_source_weight),
        )
    del views

    redis_repository = PortalRecommendationRedisRepositoryImpl()
    pool_version = str(int(generation))
    previous_pool_state = await redis_repository.get_pool_state(tenant_id)
    previous_pool_version = previous_pool_state.active_pool_version or ""
    pools, projection_count, personal_projection_excluded_count = await _prepare_pool_candidates(
        redis_repository=redis_repository, tenant_id=tenant_id, previous_pool_version=previous_pool_version,
        now=now, personal_space_ids=personal_space_ids, decayed=decayed,
    )
    del decayed
    built_counts: dict[str, int] = {}
    projection_samples: set[tuple[int, int]] = set()

    async def write_pool(name: str, source: _BoundedPoolCandidates, *, domain: bool) -> None:
        assembled, next_states = source.finish(domain=domain)
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

    await write_pool("generic", pools["generic"], domain=False)
    domain_codes = sorted(name.removeprefix("domain:") for name in pools if name.startswith("domain:"))
    for domain_code in domain_codes:
        await write_pool(
            f"domain:{domain_code}",
            pools[f"domain:{domain_code}"],
            domain=True,
        )

    latest = await ShougangPortalConfigService.get_config(tenant_id=tenant_id)
    if latest is None:
        log_result(
            "discarded",
            "config_missing_after_build",
            domain_count=len(domain_codes),
            projection_count=projection_count,
        )
        return False
    if int(latest.version) != int(config_version):
        log_result(
            "discarded",
            "config_version_changed_after_build",
            actual_config_version=int(latest.version),
            domain_count=len(domain_codes),
            projection_count=projection_count,
        )
        return False
    latest_fingerprint = recommendation_config_fingerprint(
        latest.portal.recommendation.hot_half_life_days,
        latest.portal.recommendation.home_entry_source_weight,
    )
    if latest_fingerprint != fingerprint:
        log_result(
            "discarded",
            "config_fingerprint_changed_after_build",
            domain_count=len(domain_codes),
            projection_count=projection_count,
        )
        return False
    if not await _pool_counts_match(
        redis_repository,
        tenant_id=tenant_id,
        pool_version=pool_version,
        expected_counts=built_counts,
    ):
        log_result(
            "discarded",
            "pool_count_mismatch",
            built_pool_count=len(built_counts),
            candidate_count=projection_count,
            domain_count=len(domain_codes),
            projection_count=projection_count,
        )
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
            log_result(
                "discarded",
                "projection_sample_invalid",
                candidate_count=projection_count,
                domain_count=len(domain_codes),
                projection_count=projection_count,
                sample_count=len(projection_samples),
            )
            return False
    latest_pool_state = await redis_repository.get_pool_state(tenant_id)
    if (
        int(latest_pool_state.desired_generation) != int(generation)
        or int(latest_pool_state.active_generation) >= int(generation)
    ):
        log_result(
            "discarded",
            "generation_superseded",
            active_generation=int(latest_pool_state.active_generation),
            candidate_count=projection_count,
            desired_generation=int(latest_pool_state.desired_generation),
            domain_count=len(domain_codes),
            projection_count=projection_count,
        )
        return False
    await redis_repository.mark_pool_version_ready(tenant_id, pool_version)
    activated = await redis_repository.activate_pool_if_current(
        tenant_id,
        int(generation),
        pool_version,
        fingerprint,
    )
    log_result(
        "success" if activated else "discarded",
        "activated" if activated else "activation_cas_failed",
        built_pool_count=len(built_counts),
        candidate_count=projection_count,
        domain_count=len(domain_codes),
        pool_entry_count=sum(built_counts.values()),
        personal_projection_excluded_count=personal_projection_excluded_count,
        projection_count=projection_count,
        recent_view_count=recent_view_count,
    )
    return activated


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
    request_id: str,
    requested_at: float,
):
    return run_async_task(
        lambda: _rebuild_pool_request_async(
            request_id=request_id,
            requested_at=requested_at,
        )
    )


async def _rebuild_pool_request_async(*, request_id: str, requested_at: float) -> bool:
    now = time.time()
    if not math.isfinite(requested_at) or requested_at > now + 60:
        raise ValueError("invalid pool rebuild request timestamp")
    ttl_seconds = math.ceil(requested_at + POOL_REQUEST_RETENTION_SECONDS - now)
    if ttl_seconds <= 0:
        logger.info("portal recommendation pool request expired request_id={}", request_id)
        return False
    tenant_id = int(get_current_tenant_id() or DEFAULT_TENANT_ID)
    redis_repository = PortalRecommendationRedisRepositoryImpl()
    context = await redis_repository.get_pool_rebuild_request(tenant_id, request_id)
    if context is None:
        config = await ShougangPortalConfigService.get_config(tenant_id=tenant_id)
        if config is None:
            return False
        recommendation = config.portal.recommendation
        context = await redis_repository.get_or_create_pool_rebuild_request(
            tenant_id,
            request_id,
            config_version=int(config.version),
            fingerprint=recommendation_config_fingerprint(
                recommendation.hot_half_life_days,
                recommendation.home_entry_source_weight,
            ),
            ttl_seconds=ttl_seconds,
        )
    state = await redis_repository.get_pool_state(tenant_id)
    if state.desired_generation != context.generation:
        return False
    if state.active_generation == context.generation:
        return True
    return await _rebuild_shared_pools_async(
        generation=context.generation,
        config_version=context.config_version,
        fingerprint=context.fingerprint,
    )


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
                await projection_service.refresh_batch([
                    {"file_id": source.file_id,
                     "projection_version": projection_service.projection_version_for(source)}
                    for source in page
                ], sources=page)
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
    return await projection_repository.apply_batch([
        PortalRecommendationProjectionDelete(record.file_id, int(record.projection_version) + 1)
        for record in page if record.file_id not in present_ids
    ])


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
                await projection_service.refresh_batch([
                    {"file_id": source.file_id,
                     "projection_version": _projection_version_for_event(projection_service, source, reconcile_version)}
                    for source in page
                ], sources=page)
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
    async with get_async_db_session() as session:
        user_ids = await PortalRecommendationSourceRepositoryImpl(session).primary_department_user_ids(department_ids)
    return await _invalidate_user_ids_async(user_ids, tenant_id=tenant_id)


async def _invalidate_user_ids_async(
    user_ids: list[int],
    *,
    tenant_id: int | None = None,
) -> int:
    resolved_tenant_id = int(tenant_id or get_current_tenant_id() or DEFAULT_TENANT_ID)
    repository = PortalRecommendationRedisRepositoryImpl()
    normalized_ids = sorted({int(value) for value in user_ids})
    return await repository.invalidate_users(resolved_tenant_id, normalized_ids)


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
    "pools": rebuild_shared_pools_celery,
    "incremental": reconcile_incremental_celery,
    "full": reconcile_full_celery,
    "purge": purge_expired_searches_celery,
}


async def _fanout_maintenance_async(kind: str) -> int:
    task = _MAINTENANCE_TASKS.get(kind)
    if task is None:
        raise ValueError("unknown portal recommendation maintenance kind")
    tenant_ids = [DEFAULT_TENANT_ID, *(await TenantDao.aget_children_ids_active(DEFAULT_TENANT_ID))]
    if kind == "pools":
        for tenant_id in sorted(set(tenant_ids)):
            enqueue_portal_recommendation_pool_rebuild(tenant_id=tenant_id)
    else:
        _dispatch_task_for_tenants(task, tenant_ids)
    return len(set(tenant_ids))


@bisheng_celery.task(
    name="bisheng.worker.knowledge.portal_recommendation.fanout_portal_recommendation_maintenance"
)
def fanout_portal_recommendation_maintenance(kind: str):
    return run_async_task(lambda: _fanout_maintenance_async(kind))
