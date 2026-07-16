"""Rule filtering + user-day dedup for the portal hot-search pipeline (F048)."""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import timezone
from zoneinfo import ZoneInfo

from bisheng.knowledge.domain.schemas.portal_hot_search_schema import (
    CleanedSearchRecord,
    PortalSearchRecord,
)
from bisheng.knowledge.domain.services.portal_hot_search_text_utils import (
    count_han,
    has_letter_or_han,
    normalize_hot_search_query,
)

_PHONE_RE = re.compile(r"1[3-9]\d{9}")
_ID_CARD_RE = re.compile(r"\b\d{17}[\dXx]\b")

_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


class PortalHotSearchFilterService:
    """Excludes invalid content and collapses same-user same-day repeats.

    Cleaning runs before dedup so that punctuation/full-width variants of the
    same query collapse into a single user-day record.
    """

    def __init__(self, *, min_han: int = 2, max_han: int = 50) -> None:
        self.min_han = min_han
        self.max_han = max_han

    def is_valid_query(self, cleaned_query: str) -> bool:
        """Whether a cleaned query passes all content rules."""
        if not cleaned_query:
            return False
        han = count_han(cleaned_query)
        if han < self.min_han or han > self.max_han:
            return False
        if not has_letter_or_han(cleaned_query):
            # Pure digits / symbols.
            return False
        if _PHONE_RE.search(cleaned_query):
            return False
        if _ID_CARD_RE.search(cleaned_query):
            return False
        return True

    def filter_and_dedup(
        self,
        records: Iterable[PortalSearchRecord],
    ) -> list[CleanedSearchRecord]:
        """Clean, drop invalid queries, then dedup by (user, cleaned query, day)."""
        seen: dict[tuple[int, str, object], CleanedSearchRecord] = {}
        for record in records:
            cleaned = normalize_hot_search_query(record.query or record.normalized_query or "")
            if not self.is_valid_query(cleaned):
                continue
            searched_at = record.searched_at
            if searched_at.tzinfo is None:
                searched_at = searched_at.replace(tzinfo=timezone.utc)
            local_date = searched_at.astimezone(_SHANGHAI_TZ).date()
            key = (int(record.user_id), cleaned, local_date)
            existing = seen.get(key)
            if existing is None or searched_at < existing.searched_at:
                seen[key] = CleanedSearchRecord(
                    user_id=int(record.user_id),
                    cleaned_query=cleaned,
                    searched_at=searched_at,
                    local_date=local_date,
                )
        return list(seen.values())
