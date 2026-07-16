from __future__ import annotations

import math
from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from bisheng.knowledge.domain.services.portal_recommendation_service import PortalRecommendationCandidate


@dataclass(frozen=True, slots=True)
class PortalRecommendationPoolState:
    active_since: date
    cooldown_until: date | None = None


@dataclass(frozen=True, slots=True)
class PortalRecommendationView:
    user_id: int
    file_id: int
    viewed_at: datetime
    source: str


class PortalRecommendationPoolService:
    BUSINESS_TIMEZONE = ZoneInfo("Asia/Shanghai")
    ACTIVE_DAYS = 14
    COOLDOWN_DAYS = 3
    WINDOW_DAYS = 30

    @staticmethod
    def interleave_hot_fresh(
        hot: Sequence[PortalRecommendationCandidate],
        fresh: Sequence[PortalRecommendationCandidate],
        *,
        limit: int = 500,
    ) -> list[PortalRecommendationCandidate]:
        hot_queue = deque(hot)
        fresh_queue = deque(fresh)
        seen: set[tuple[int, int]] = set()
        result: list[PortalRecommendationCandidate] = []

        def take(queue: deque[PortalRecommendationCandidate], count: int) -> None:
            added = 0
            while queue and added < count and len(result) < limit:
                candidate = queue.popleft()
                if candidate.key in seen:
                    continue
                seen.add(candidate.key)
                result.append(candidate)
                added += 1

        while len(result) < limit and (hot_queue or fresh_queue):
            before = len(result)
            take(hot_queue, 3)
            take(fresh_queue, 1)
            if not hot_queue:
                take(fresh_queue, limit - len(result))
            elif not fresh_queue:
                take(hot_queue, limit - len(result))
            if len(result) == before:
                break
        return result

    @staticmethod
    def round_robin_limit(
        pools: Mapping[str, Sequence[PortalRecommendationCandidate]],
        *,
        limit: int = 10_000,
    ) -> list[PortalRecommendationCandidate]:
        queues = [(name, deque(items)) for name, items in sorted(pools.items())]
        seen: set[tuple[int, int]] = set()
        result: list[PortalRecommendationCandidate] = []
        while queues and len(result) < limit:
            remaining = []
            for name, queue in queues:
                while queue:
                    candidate = queue.popleft()
                    if candidate.key in seen:
                        continue
                    seen.add(candidate.key)
                    result.append(candidate)
                    break
                if queue:
                    remaining.append((name, queue))
                if len(result) >= limit:
                    break
            queues = remaining
        return result

    @classmethod
    def is_rotation_active(cls, state: PortalRecommendationPoolState, today: date) -> bool:
        if state.cooldown_until is not None:
            return today >= state.cooldown_until
        return today < state.active_since + timedelta(days=cls.ACTIVE_DAYS)

    @classmethod
    def advance_rotation(cls, state: PortalRecommendationPoolState, today: date) -> PortalRecommendationPoolState:
        if state.cooldown_until is None and today >= state.active_since + timedelta(days=cls.ACTIVE_DAYS):
            return PortalRecommendationPoolState(
                active_since=state.active_since,
                cooldown_until=today + timedelta(days=cls.COOLDOWN_DAYS),
            )
        if state.cooldown_until is not None and today >= state.cooldown_until:
            return PortalRecommendationPoolState(active_since=today)
        return state

    @classmethod
    def rotate_hot_candidates(
        cls,
        candidates: Sequence[PortalRecommendationCandidate],
        *,
        states: Mapping[tuple[int, int], PortalRecommendationPoolState],
        today: date,
    ) -> tuple[
        list[PortalRecommendationCandidate],
        dict[tuple[int, int], PortalRecommendationPoolState],
        int,
    ]:
        """Apply each pool's independent 14-day active / 3-day cooldown cycle."""
        eligible: list[PortalRecommendationCandidate] = []
        next_states: dict[tuple[int, int], PortalRecommendationPoolState] = {}
        filtered = 0
        for candidate in candidates:
            state = states.get(candidate.key)
            if state is None:
                eligible.append(candidate)
                continue
            state = cls.advance_rotation(state, today)
            next_states[candidate.key] = state
            if cls.is_rotation_active(state, today):
                eligible.append(candidate)
            else:
                filtered += 1
        return eligible, next_states, filtered

    @classmethod
    def business_date(cls, value: datetime) -> date:
        """Return the portal business day, independent of the worker host timezone."""
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(cls.BUSINESS_TIMEZONE).date()

    @classmethod
    def decayed_view_count(
        cls,
        views: Iterable[PortalRecommendationView],
        *,
        now: datetime | None = None,
        half_life_days: float,
        recommendation_source_weight: float,
    ) -> float:
        if half_life_days <= 0:
            raise ValueError("half_life_days must be positive")
        now = now or datetime.now(timezone.utc)
        unique: dict[tuple[int, int, date], PortalRecommendationView] = {}
        for view in views:
            viewed_at = view.viewed_at
            if viewed_at.tzinfo is None:
                viewed_at = viewed_at.replace(tzinfo=timezone.utc)
            age_days = (now - viewed_at).total_seconds() / 86400
            if age_days < 0 or age_days > cls.WINDOW_DAYS:
                continue
            key = (view.user_id, view.file_id, cls.business_date(viewed_at))
            current = unique.get(key)
            if current is None or viewed_at > current.viewed_at:
                unique[key] = PortalRecommendationView(view.user_id, view.file_id, viewed_at, view.source)

        total = 0.0
        recommendation_sources = {"home_recommendation", "recommendation_list", "unknown"}
        for view in unique.values():
            age_days = max((now - view.viewed_at).total_seconds(), 0) / 86400
            source_weight = recommendation_source_weight if view.source in recommendation_sources else 1.0
            total += source_weight * math.pow(2, -age_days / half_life_days)
        return total
