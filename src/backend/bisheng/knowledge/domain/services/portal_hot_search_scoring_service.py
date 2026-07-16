"""Heat scoring + qualification for the portal hot-search pipeline (F048)."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import datetime
from zoneinfo import ZoneInfo

from bisheng.knowledge.domain.schemas.portal_hot_search_schema import (
    CleanedSearchRecord,
    HotSearchIntentGroup,
    HotSearchRankItem,
)

_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def intent_key_for(canonical_query: str) -> str:
    """Stable short hash used to identify an intent group across tables."""
    return hashlib.sha256(canonical_query.encode("utf-8")).hexdigest()[:16]


class PortalHotSearchScoringService:
    """Scores intent groups: 2 pts per deduped record in the last 7 days,
    1 pt in days 8-30, with per-user-per-day dedup at the intent level.
    """

    def __init__(
        self,
        *,
        min_unique_users: int = 5,
        min_search_count: int = 8,
        window_days: int = 30,
        recent_days: int = 7,
    ) -> None:
        self.min_unique_users = min_unique_users
        self.min_search_count = min_search_count
        self.window_days = window_days
        self.recent_days = recent_days

    def score(
        self,
        groups: Sequence[HotSearchIntentGroup],
        records: Sequence[CleanedSearchRecord],
        *,
        now: datetime,
        top_k: int = 5,
    ) -> list[HotSearchRankItem]:
        query_to_group: dict[str, HotSearchIntentGroup] = {}
        for group in groups:
            for member in group.member_queries:
                query_to_group[member] = group

        today = now.astimezone(_SHANGHAI_TZ).date()
        # Intent-level user-day dedup: {intent_key: {(user_id, local_date)}}.
        dedup: dict[str, set[tuple[int, object]]] = {}
        recent_counts: dict[str, int] = {}
        older_counts: dict[str, int] = {}
        users: dict[str, set[int]] = {}
        group_by_key: dict[str, HotSearchIntentGroup] = {}

        for record in records:
            group = query_to_group.get(record.cleaned_query)
            if group is None:
                continue
            key = group.intent_key
            group_by_key.setdefault(key, group)
            dedup_key = (record.user_id, record.local_date)
            bucket = dedup.setdefault(key, set())
            if dedup_key in bucket:
                continue
            bucket.add(dedup_key)
            age_days = (today - record.local_date).days
            if age_days < 0 or age_days >= self.window_days:
                continue
            users.setdefault(key, set()).add(record.user_id)
            if age_days < self.recent_days:
                recent_counts[key] = recent_counts.get(key, 0) + 1
            else:
                older_counts[key] = older_counts.get(key, 0) + 1

        items: list[HotSearchRankItem] = []
        for key, group in group_by_key.items():
            count_7d = recent_counts.get(key, 0)
            count_8_30d = older_counts.get(key, 0)
            total = count_7d + count_8_30d
            if total == 0:
                continue
            unique_users = len(users.get(key, set()))
            heat = 2 * count_7d + count_8_30d
            qualified = unique_users >= self.min_unique_users and total >= self.min_search_count
            items.append(
                HotSearchRankItem(
                    intent_key=key,
                    canonical_query=group.canonical_query,
                    display_query=group.canonical_query,
                    heat_score=heat,
                    unique_users=unique_users,
                    search_count_7d=count_7d,
                    search_count_8_30d=count_8_30d,
                    qualified=qualified,
                    member_queries=list(group.member_queries),
                )
            )

        items.sort(key=lambda i: (-i.heat_score, -i.unique_users, i.canonical_query))
        rank = 0
        for item in items:
            if item.qualified and rank < top_k:
                rank += 1
                item.final_rank = rank
        return items
