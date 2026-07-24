"""Persist tag-library candidates in the shared ``tag`` table."""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import datetime
from difflib import SequenceMatcher
from typing import Literal

from loguru import logger
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlmodel import delete, func, select, update

from bisheng.core.database import get_async_db_session, get_sync_db_session
from bisheng.database.models.group_resource import ResourceTypeEnum
from bisheng.database.models.review_tags import ReviewTag, ReviewTagLink
from bisheng.database.models.tag import (
    Tag,
    TagBusinessTypeEnum,
    TagDao,
    TagLink,
    TagResourceTypeEnum,
)
from bisheng.knowledge.domain.models.knowledge_tag_library_link import (
    KnowledgeTagLibraryLinkDao,
)
from bisheng.knowledge.domain.schemas.knowledge_space_tag_library_schema import KnowledgeSpaceTagLibraryTreeItem
from bisheng.knowledge.domain.schemas.link_b_tag_resolver_schema import (
    PendingReviewTagMatch,
    ResolvedTagCandidate,
    TagMatchKind,
    TagNameCatalogEntry,
    TagResolutionBatch,
)

PENDING_REVIEW_TAG_SIMILARITY_THRESHOLD = 0.85
TAG_SIMILARITY_MIN_LENGTH = 3
TAG_SUBSTRING_MIN_LENGTH = 2
LINK_B_L3_MAX_CANDIDATES = 200
LINK_B_PROMPT_CATALOG_LIMIT = 200


class TagLibraryTagService:
    _RESOURCE_TYPE_DISPLAY_PRIORITY: dict[str, int] = {
        TagResourceTypeEnum.SYSTEM_TAG.value: 3,
        TagResourceTypeEnum.AI_AUTO_TAG.value: 2,
        TagResourceTypeEnum.MANUAL_TAG.value: 1,
    }

    @staticmethod
    def _business_id(library_id: int) -> str:
        return str(library_id)

    @classmethod
    def _resource_type_priority(cls, resource_type: str | None) -> int:
        return cls._RESOURCE_TYPE_DISPLAY_PRIORITY.get((resource_type or "").strip().lower(), 0)

    @classmethod
    def dedupe_non_ai_tag_name_lists(
        cls,
        system_tags: Iterable[str] | None,
        manual_tags: Iterable[str] | None,
    ) -> tuple[list[str], list[str]]:
        """System names win; drop manual entries that duplicate a system name."""
        system = cls._normalize_names(system_tags or [])
        system_set = set(system)
        manual = [name for name in cls._normalize_names(manual_tags or []) if name not in system_set]
        return system, manual

    @classmethod
    def dedupe_library_tags_by_name(cls, tags: list[Tag]) -> list[Tag]:
        """Keep one tag row per name; system_tag > ai_auto_tag > manual_tag."""
        best_by_name: dict[str, Tag] = {}
        for tag in tags:
            name = (tag.name or "").strip()
            if not name:
                continue
            key = name.lower()
            existing = best_by_name.get(key)
            if existing is None or cls._resource_type_priority(tag.resource_type) > cls._resource_type_priority(
                existing.resource_type
            ):
                best_by_name[key] = tag
        return list(best_by_name.values())

    @staticmethod
    def normalize_tag_name_key(name: str) -> str:
        text = unicodedata.normalize("NFKC", (name or "").strip())
        return re.sub(r"\s+", "", text)

    @staticmethod
    def find_exact_tag_name(
        candidate: str,
        catalog_by_key: dict[str, str],
    ) -> tuple[str | None, Literal["exact", "new"]]:
        key = TagLibraryTagService.normalize_tag_name_key(candidate)
        if not key:
            return None, "new"
        canonical = catalog_by_key.get(key)
        if canonical:
            return canonical, "exact"
        return None, "new"

    @classmethod
    def find_similar_tag_name(
        cls,
        candidate: str,
        catalog_entries: Sequence[tuple[str, str]],
        *,
        similarity_threshold: float = PENDING_REVIEW_TAG_SIMILARITY_THRESHOLD,
        allow_substring: bool = True,
        max_l3_candidates: int = LINK_B_L3_MAX_CANDIDATES,
    ) -> tuple[str | None, TagMatchKind, float | None]:
        candidate_key = cls.normalize_tag_name_key(candidate)
        if not candidate_key:
            return None, "new", None

        for canonical_name, catalog_key in catalog_entries:
            if catalog_key and catalog_key == candidate_key:
                return canonical_name, "exact", 1.0

        if allow_substring:
            substring_hits: list[tuple[str, str]] = []
            for canonical_name, catalog_key in catalog_entries:
                if not catalog_key:
                    continue
                shorter, longer = (
                    (candidate_key, catalog_key)
                    if len(candidate_key) <= len(catalog_key)
                    else (catalog_key, candidate_key)
                )
                if len(shorter) < TAG_SUBSTRING_MIN_LENGTH:
                    continue
                if shorter in longer:
                    substring_hits.append((canonical_name, catalog_key))
            if substring_hits:
                canonical_name, _ = max(substring_hits, key=lambda item: len(item[1]))
                return canonical_name, "substring", None

        if len(candidate_key) < TAG_SIMILARITY_MIN_LENGTH:
            return None, "new", None

        l3_pool: list[tuple[str, str]] = []
        for canonical_name, catalog_key in catalog_entries:
            if not catalog_key or len(catalog_key) < TAG_SIMILARITY_MIN_LENGTH:
                continue
            if abs(len(candidate_key) - len(catalog_key)) > 4:
                continue
            if candidate_key[0] != catalog_key[0]:
                continue
            l3_pool.append((canonical_name, catalog_key))

        if len(l3_pool) > max_l3_candidates:
            l3_pool = l3_pool[:max_l3_candidates]

        best_name: str | None = None
        best_score: float | None = None
        for canonical_name, catalog_key in l3_pool:
            score = SequenceMatcher(None, candidate_key, catalog_key).ratio()
            if score >= similarity_threshold and (best_score is None or score > best_score):
                best_name = canonical_name
                best_score = score

        if best_name is not None:
            return best_name, "similarity", best_score
        return None, "new", None

    @classmethod
    def dedupe_pending_review_tags_by_name(cls, tags: list[ReviewTag]) -> list[ReviewTag]:
        best_by_name: dict[str, ReviewTag] = {}
        for tag in tags:
            name = (tag.name or "").strip()
            if not name:
                continue
            key = name.lower()
            existing = best_by_name.get(key)
            if existing is None:
                best_by_name[key] = tag
                continue
            existing_priority = cls._resource_type_priority(existing.resource_type)
            tag_priority = cls._resource_type_priority(tag.resource_type)
            if tag_priority > existing_priority:
                best_by_name[key] = tag
            elif tag_priority == existing_priority and (tag.id or 0) < (existing.id or 0):
                best_by_name[key] = tag
        return list(best_by_name.values())

    @classmethod
    def _pick_best_library_tag_from_rows(cls, rows: list[Tag]) -> Tag | None:
        if not rows:
            return None
        deduped = cls.dedupe_library_tags_by_name(rows)
        return deduped[0] if deduped else None

    @classmethod
    def list_tenant_library_tag_catalog_sync(cls, tenant_id: int | None) -> list[TagNameCatalogEntry]:
        if tenant_id is None:
            return []
        with get_sync_db_session() as session:
            rows = session.exec(
                select(Tag).where(
                    Tag.tenant_id == tenant_id,
                    Tag.business_type == TagBusinessTypeEnum.TAG_LIBRARY.value,
                )
            ).all()
        deduped_tags = cls.dedupe_library_tags_by_name(list(rows))
        return [
            TagNameCatalogEntry(
                canonical_name=(tag.name or "").strip(),
                normalized_key=cls.normalize_tag_name_key(tag.name),
                resource_type=tag.resource_type,
            )
            for tag in deduped_tags
            if (tag.name or "").strip()
        ]

    @classmethod
    def build_tenant_library_by_key_sync(cls, tenant_id: int | None) -> dict[str, str]:
        return {
            entry.normalized_key: entry.canonical_name for entry in cls.list_tenant_library_tag_catalog_sync(tenant_id)
        }

    @classmethod
    def list_tenant_pending_review_catalog_sync(
        cls,
        tenant_id: int | None,
        resource_type: TagResourceTypeEnum = TagResourceTypeEnum.AI_AUTO_TAG,
    ) -> list[ReviewTag]:
        if tenant_id is None:
            return []
        library_name_subq = select(Tag.name).where(
            Tag.business_type == TagBusinessTypeEnum.TAG_LIBRARY.value,
            Tag.tenant_id == tenant_id,
        )
        statement = select(ReviewTag).where(
            ReviewTag.tenant_id == tenant_id,
            ReviewTag.review_status == 0,
            ReviewTag.is_deleted == False,
            ReviewTag.resource_type == resource_type.value,
            ReviewTag.name.not_in(library_name_subq),
        )
        with get_sync_db_session() as session:
            rows = session.exec(statement).all()
        return cls.dedupe_pending_review_tags_by_name(list(rows))

    @classmethod
    def find_exact_tenant_library_tag_sync(
        cls,
        *,
        tenant_id: int | None,
        tag_name: str,
        catalog_by_key: dict[str, str] | None = None,
    ) -> tuple[str | None, Literal["exact", "new"]]:
        by_key = catalog_by_key if catalog_by_key is not None else cls.build_tenant_library_by_key_sync(tenant_id)
        return cls.find_exact_tag_name(tag_name, by_key)

    @classmethod
    def _pending_catalog_entries(cls, catalog: Sequence[ReviewTag]) -> list[tuple[str, str]]:
        return [
            ((tag.name or "").strip(), cls.normalize_tag_name_key(tag.name))
            for tag in catalog
            if (tag.name or "").strip()
        ]

    @classmethod
    def find_similar_tenant_pending_review_tag_sync(
        cls,
        *,
        tenant_id: int | None,
        tag_name: str,
        resource_type: TagResourceTypeEnum = TagResourceTypeEnum.AI_AUTO_TAG,
        catalog: Sequence[ReviewTag] | None = None,
        similarity_threshold: float = PENDING_REVIEW_TAG_SIMILARITY_THRESHOLD,
        allow_substring: bool = True,
    ) -> PendingReviewTagMatch | None:
        candidate = (tag_name or "").strip()
        if not candidate:
            return None

        pending_catalog = (
            list(catalog)
            if catalog is not None
            else cls.list_tenant_pending_review_catalog_sync(tenant_id, resource_type)
        )
        if not pending_catalog:
            return None

        tag_by_canonical = {(tag.name or "").strip(): tag for tag in pending_catalog if (tag.name or "").strip()}
        canonical_name, match_kind, score = cls.find_similar_tag_name(
            candidate,
            cls._pending_catalog_entries(pending_catalog),
            similarity_threshold=similarity_threshold,
            allow_substring=allow_substring,
        )
        if not canonical_name or match_kind == "new":
            return None

        review_tag = tag_by_canonical.get(canonical_name)
        if review_tag is None:
            return None

        if match_kind != "exact":
            logger.info(
                "review_tag_reuse_pending tenant_id={} original={} canonical={} match_kind={} score={} review_tag_id={}",
                tenant_id,
                candidate,
                canonical_name,
                match_kind,
                score,
                review_tag.id,
            )
        return PendingReviewTagMatch(
            review_tag=review_tag,
            original=candidate,
            canonical_name=canonical_name,
            match_kind=match_kind,
            score=score,
        )

    @classmethod
    def resolve_link_b_tag_candidates_sync(
        cls,
        *,
        tenant_id: int | None,
        candidates: Iterable[str],
        resource_type: TagResourceTypeEnum = TagResourceTypeEnum.AI_AUTO_TAG,
        library_by_key: dict[str, str] | None = None,
        pending_catalog: Sequence[ReviewTag] | None = None,
    ) -> TagResolutionBatch:
        if tenant_id is None:
            return TagResolutionBatch()

        library_index = (
            library_by_key if library_by_key is not None else cls.build_tenant_library_by_key_sync(tenant_id)
        )
        pending_rows = (
            list(pending_catalog)
            if pending_catalog is not None
            else cls.list_tenant_pending_review_catalog_sync(tenant_id, resource_type)
        )

        entries: list[ResolvedTagCandidate] = []
        seen_canonical: set[str] = set()

        for raw_candidate in candidates:
            candidate = (raw_candidate or "").strip()
            if not candidate:
                continue

            canonical, library_kind = cls.find_exact_tenant_library_tag_sync(
                tenant_id=tenant_id,
                tag_name=candidate,
                catalog_by_key=library_index,
            )
            if canonical and library_kind == "exact":
                if canonical not in seen_canonical:
                    seen_canonical.add(canonical)
                    entries.append(
                        ResolvedTagCandidate(
                            original=candidate,
                            canonical_name=canonical,
                            target="approved",
                            match_kind="exact",
                            score=1.0,
                        )
                    )
                    logger.info(
                        "review_tag_reuse_library tenant_id={} original={} canonical={} match_kind={} score={}",
                        tenant_id,
                        candidate,
                        canonical,
                        "exact",
                        1.0,
                    )
                continue

            pending_match = cls.find_similar_tenant_pending_review_tag_sync(
                tenant_id=tenant_id,
                tag_name=candidate,
                resource_type=resource_type,
                catalog=pending_rows,
            )
            if pending_match:
                canonical = pending_match.canonical_name
                if canonical not in seen_canonical:
                    seen_canonical.add(canonical)
                    entries.append(
                        ResolvedTagCandidate(
                            original=candidate,
                            canonical_name=canonical,
                            target="pending",
                            match_kind=pending_match.match_kind,
                            score=pending_match.score,
                        )
                    )
                continue

            if candidate not in seen_canonical:
                seen_canonical.add(candidate)
                entries.append(
                    ResolvedTagCandidate(
                        original=candidate,
                        canonical_name=candidate,
                        target="pending",
                        match_kind="new",
                        score=None,
                    )
                )

        return TagResolutionBatch(entries=entries)

    @classmethod
    def load_link_b_tenant_catalog_sync(
        cls,
        tenant_id: int | None,
        resource_type: TagResourceTypeEnum = TagResourceTypeEnum.AI_AUTO_TAG,
    ):
        from bisheng.knowledge.domain.services.link_b_tag_resolver_catalog_cache import (
            LinkBTagResolverCatalogCache,
        )

        return LinkBTagResolverCatalogCache.load_sync(tenant_id, resource_type)

    @classmethod
    def invalidate_link_b_tenant_catalog_cache_sync(cls, tenant_id: int | None) -> None:
        from bisheng.knowledge.domain.services.link_b_tag_resolver_catalog_cache import (
            LinkBTagResolverCatalogCache,
        )

        LinkBTagResolverCatalogCache.invalidate_sync(tenant_id)

    @classmethod
    async def invalidate_link_b_tenant_catalog_cache_async(cls, tenant_id: int | None) -> None:
        from bisheng.knowledge.domain.services.link_b_tag_resolver_catalog_cache import (
            LinkBTagResolverCatalogCache,
        )

        await LinkBTagResolverCatalogCache.invalidate_async(tenant_id)

    @classmethod
    def _find_tenant_pending_review_tag_exact_in_session(
        cls,
        session,
        *,
        tenant_id: int | None,
        tag_name: str,
        resource_type: TagResourceTypeEnum,
    ) -> ReviewTag | None:
        normalized = (tag_name or "").strip()
        if not normalized or tenant_id is None:
            return None
        library_name_subq = select(Tag.name).where(
            Tag.business_type == TagBusinessTypeEnum.TAG_LIBRARY.value,
            Tag.tenant_id == tenant_id,
        )
        rows = session.exec(
            select(ReviewTag).where(
                ReviewTag.tenant_id == tenant_id,
                ReviewTag.name == normalized,
                ReviewTag.is_deleted == False,
                ReviewTag.review_status == 0,
                ReviewTag.resource_type == resource_type.value,
                ReviewTag.name.not_in(library_name_subq),
            )
        ).all()
        deduped = cls.dedupe_pending_review_tags_by_name(list(rows))
        return deduped[0] if deduped else None

    @classmethod
    async def list_tags(cls, library_id: int) -> list[Tag]:
        tags = await TagDao.get_tags_by_business(
            TagBusinessTypeEnum.TAG_LIBRARY,
            cls._business_id(library_id),
        )
        return await cls._repair_legacy_library_resource_types(tags)

    @classmethod
    async def _repair_legacy_library_resource_types(cls, tags: list[Tag]) -> list[Tag]:
        """Upgrade pre-2.6 libraries that stored every candidate as manual_tag.

        Old ``replace_tags`` wrote all non-AI library tags with ``manual_tag`` while the
        product treated them as system tags in the UI. Once display mapping was fixed,
        those rows looked like human/manual tags. Only auto-repair libraries that still
        have *no* ``system_tag`` rows (mixed libraries already use the new model).
        """
        if not tags:
            return tags
        if any(tag.resource_type == TagResourceTypeEnum.SYSTEM_TAG.value for tag in tags):
            return cls.dedupe_library_tags_by_name(tags)

        legacy_manual = [
            tag for tag in tags if tag.resource_type == TagResourceTypeEnum.MANUAL_TAG.value and tag.id is not None
        ]
        if not legacy_manual:
            return tags

        async with get_async_db_session() as session:
            for tag in legacy_manual:
                tag.resource_type = TagResourceTypeEnum.SYSTEM_TAG.value
                session.add(tag)
            await session.commit()

        for tag in legacy_manual:
            tag.resource_type = TagResourceTypeEnum.SYSTEM_TAG.value
        return cls.dedupe_library_tags_by_name(tags)

    @classmethod
    def _repair_legacy_library_resource_types_sync(cls, tags: list[Tag]) -> list[Tag]:
        if not tags:
            return tags
        if any(tag.resource_type == TagResourceTypeEnum.SYSTEM_TAG.value for tag in tags):
            return cls.dedupe_library_tags_by_name(tags)

        legacy_manual = [
            tag for tag in tags if tag.resource_type == TagResourceTypeEnum.MANUAL_TAG.value and tag.id is not None
        ]
        if not legacy_manual:
            return tags

        with get_sync_db_session() as session:
            for tag in legacy_manual:
                tag.resource_type = TagResourceTypeEnum.SYSTEM_TAG.value
                session.add(tag)
            session.commit()

        for tag in legacy_manual:
            tag.resource_type = TagResourceTypeEnum.SYSTEM_TAG.value
        return cls.dedupe_library_tags_by_name(tags)

    @staticmethod
    def _file_resource_types(library_resource_type: str) -> list[str]:
        if library_resource_type == TagResourceTypeEnum.MANUAL_TAG.value:
            return [TagResourceTypeEnum.SYSTEM_TAG.value, TagResourceTypeEnum.MANUAL_TAG.value]
        if library_resource_type == TagResourceTypeEnum.SYSTEM_TAG.value:
            return [TagResourceTypeEnum.SYSTEM_TAG.value, TagResourceTypeEnum.MANUAL_TAG.value]
        if library_resource_type == TagResourceTypeEnum.AI_AUTO_TAG.value:
            return [TagResourceTypeEnum.AI_AUTO_TAG.value]
        return [library_resource_type]

    @classmethod
    def _library_usage_items(
        cls,
        *,
        tags: list[Tag],
        system_tags: list[str] | None = None,
        manual_tags: list[str] | None = None,
        ai_tags: list[str] | None = None,
    ) -> list[tuple[str, str]]:
        if tags:
            return [(tag.name or "", tag.resource_type) for tag in tags if tag.name]
        items: list[tuple[str, str]] = [
            (name, TagResourceTypeEnum.SYSTEM_TAG.value) for name in (system_tags or []) if name
        ]
        items.extend((name, TagResourceTypeEnum.MANUAL_TAG.value) for name in (manual_tags or []) if name)
        items.extend((name, TagResourceTypeEnum.AI_AUTO_TAG.value) for name in (ai_tags or []) if name)
        return items

    @staticmethod
    def _existing_tag_meta(
        existing_meta: dict[tuple[str, str], tuple],
        name: str,
        resource_type: str,
    ) -> tuple:
        if (name, resource_type) in existing_meta:
            return existing_meta[(name, resource_type)]
        for alt_type in (TagResourceTypeEnum.SYSTEM_TAG.value, TagResourceTypeEnum.MANUAL_TAG.value):
            if alt_type != resource_type and (name, alt_type) in existing_meta:
                return existing_meta[(name, alt_type)]
        return None, None

    @classmethod
    async def _resolve_file_tag_ids(
        cls,
        *,
        items: Iterable[tuple[str, str]],
        tenant_id: int | None,
        library_id: int | None = None,
    ) -> list[int]:
        normalized_items = [(name, resource_type) for name, resource_type in items if name]
        if not normalized_items or tenant_id is None:
            return []

        names = list(dict.fromkeys(name for name, _ in normalized_items))
        file_types = list(
            dict.fromkeys(
                file_type
                for _, library_type in normalized_items
                for file_type in cls._file_resource_types(library_type)
            )
        )

        scope_filters = [
            Tag.name.in_(names),
            Tag.tenant_id == tenant_id,
            Tag.resource_type.in_(file_types),
        ]
        if library_id is not None:
            library_business_id = cls._business_id(library_id)
            scope_filters.append(
                or_(
                    Tag.business_type != TagBusinessTypeEnum.TAG_LIBRARY.value,
                    Tag.business_id == library_business_id,
                )
            )

        async with get_async_db_session() as session:
            tag_ids = (await session.exec(select(Tag.id).where(*scope_filters))).all()
        return [int(tag_id) for tag_id in tag_ids]

    @classmethod
    async def count_usage_batch(
        cls,
        *,
        items: Iterable[tuple[str, str]],
        tenant_id: int | None,
        library_id: int | None = None,
    ) -> dict[tuple[str, str], int]:
        """Count tag_link rows for file tags matching library candidates."""
        normalized_items = [(name, resource_type) for name, resource_type in items if name]
        if not normalized_items or tenant_id is None:
            return {}

        tag_ids = await cls._resolve_file_tag_ids(
            items=normalized_items,
            tenant_id=tenant_id,
            library_id=library_id,
        )
        if not tag_ids:
            return dict.fromkeys(normalized_items, 0)

        async with get_async_db_session() as session:
            tag_rows = (
                await session.exec(
                    select(Tag.id, Tag.name, Tag.resource_type).where(
                        Tag.id.in_(tag_ids),
                    )
                )
            ).all()
            link_rows = (
                await session.exec(
                    select(TagLink.tag_id, func.count(TagLink.id))
                    .where(TagLink.tag_id.in_(tag_ids), TagLink.tenant_id == tenant_id)
                    .group_by(TagLink.tag_id)
                )
            ).all()

        link_count_by_tag_id = {int(tag_id): int(count) for tag_id, count in link_rows}
        usage_by_name_and_file_type: dict[tuple[str, str], int] = defaultdict(int)
        for tag_id, name, file_resource_type in tag_rows:
            usage_by_name_and_file_type[(name, file_resource_type)] += link_count_by_tag_id.get(int(tag_id), 0)

        result: dict[tuple[str, str], int] = {}
        for name, library_resource_type in normalized_items:
            total = 0
            for file_resource_type in cls._file_resource_types(library_resource_type):
                total += usage_by_name_and_file_type.get((name, file_resource_type), 0)
            result[(name, library_resource_type)] = total
        return result

    @classmethod
    async def count_distinct_usage(
        cls,
        *,
        library_id: int,
        tenant_id: int | None,
        manual_tags: list[str] | None = None,
        ai_tags: list[str] | None = None,
    ) -> int:
        tags = await cls.list_tags(library_id)
        items = cls._library_usage_items(tags=tags, manual_tags=manual_tags, ai_tags=ai_tags)
        return await cls.count_distinct_usage_by_items(
            items=items,
            tenant_id=tenant_id,
            library_id=library_id,
        )

    @classmethod
    async def count_distinct_usage_by_items(
        cls,
        *,
        items: Iterable[tuple[str, str]],
        tenant_id: int | None,
        library_id: int | None = None,
    ) -> int:
        tag_ids = await cls._resolve_file_tag_ids(
            items=items,
            tenant_id=tenant_id,
            library_id=library_id,
        )
        if not tag_ids:
            return 0

        async with get_async_db_session() as session:
            resource_ids = (
                await session.exec(
                    select(TagLink.resource_id)
                    .where(
                        TagLink.tag_id.in_(tag_ids),
                        TagLink.tenant_id == tenant_id,
                    )
                    .distinct()
                )
            ).all()
        return len(resource_ids)

    @classmethod
    async def count_total_usage(
        cls,
        *,
        library_id: int,
        tenant_id: int | None,
        system_tags: list[str] | None = None,
        manual_tags: list[str] | None = None,
        ai_tags: list[str] | None = None,
    ) -> int:
        """Sum per-tag usage counts (matches tag dialog column semantics)."""
        tags = await cls.list_tags(library_id)
        items = cls._library_usage_items(
            tags=tags,
            system_tags=system_tags,
            manual_tags=manual_tags,
            ai_tags=ai_tags,
        )
        if not items or tenant_id is None:
            return 0
        usage_map = await cls.count_usage_batch(
            items=items,
            tenant_id=tenant_id,
            library_id=library_id,
        )
        return sum(usage_map.values())

    @classmethod
    async def list_tag_names(
        cls,
        library_id: int,
    ) -> tuple[list[str], list[str], list[str]]:
        tags = await cls.list_tags(library_id)
        system = [
            (tag.name or "").strip()
            for tag in tags
            if tag.resource_type == TagResourceTypeEnum.SYSTEM_TAG.value and (tag.name or "").strip()
        ]
        manual = [
            (tag.name or "").strip()
            for tag in tags
            if tag.resource_type == TagResourceTypeEnum.MANUAL_TAG.value and (tag.name or "").strip()
        ]
        ai = [
            (tag.name or "").strip()
            for tag in tags
            if tag.resource_type == TagResourceTypeEnum.AI_AUTO_TAG.value and (tag.name or "").strip()
        ]
        return system, manual, ai

    @classmethod
    def list_tag_names_sync(cls, library_id: int) -> tuple[list[str], list[str], list[str]]:

        statement = select(Tag).where(
            Tag.business_type == TagBusinessTypeEnum.TAG_LIBRARY.value,
            Tag.business_id == cls._business_id(library_id),
        )
        with get_sync_db_session() as session:
            tags = session.exec(statement).all()
        tags = cls._repair_legacy_library_resource_types_sync(list(tags))
        system = [
            (tag.name or "").strip()
            for tag in tags
            if tag.resource_type == TagResourceTypeEnum.SYSTEM_TAG.value and (tag.name or "").strip()
        ]
        manual = [
            (tag.name or "").strip()
            for tag in tags
            if tag.resource_type == TagResourceTypeEnum.MANUAL_TAG.value and (tag.name or "").strip()
        ]
        ai = [
            (tag.name or "").strip()
            for tag in tags
            if tag.resource_type == TagResourceTypeEnum.AI_AUTO_TAG.value and (tag.name or "").strip()
        ]
        return system, manual, ai

    @classmethod
    def non_ai_tag_names(cls, system_tags: list[str], manual_tags: list[str]) -> list[str]:
        return list(dict.fromkeys([*(system_tags or []), *(manual_tags or [])]))

    @classmethod
    async def count_tags(cls, library_id: int) -> int:
        system, manual, ai = await cls.list_tag_names(library_id)
        return len(system) + len(manual) + len(ai)

    @classmethod
    async def find_library_tag_by_name(cls, *, tenant_id: int | None, tag_name: str) -> Tag | None:
        normalized = (tag_name or "").strip()
        if not normalized or tenant_id is None:
            return None
        async with get_async_db_session() as session:
            rows = (
                await session.exec(
                    select(Tag).where(
                        Tag.business_type == TagBusinessTypeEnum.TAG_LIBRARY.value,
                        Tag.tenant_id == tenant_id,
                        Tag.name == normalized,
                    )
                )
            ).all()
        return cls._pick_best_library_tag_from_rows(list(rows))

    @classmethod
    def find_library_tag_by_name_sync(cls, *, tenant_id: int | None, tag_name: str) -> Tag | None:
        normalized = (tag_name or "").strip()
        if not normalized or tenant_id is None:
            return None
        with get_sync_db_session() as session:
            rows = session.exec(
                select(Tag).where(
                    Tag.business_type == TagBusinessTypeEnum.TAG_LIBRARY.value,
                    Tag.tenant_id == tenant_id,
                    Tag.name == normalized,
                )
            ).all()
        return cls._pick_best_library_tag_from_rows(list(rows))

    @classmethod
    def _first_library_id_for_space(cls, space_id: int) -> int | None:
        """Resolve the primary tag library for a space (same fallback chain as auto-tag)."""
        library_ids = KnowledgeTagLibraryLinkDao.list_library_ids_by_knowledge(space_id)
        if library_ids:
            return library_ids[0]
        from bisheng.knowledge.domain.models.knowledge import KnowledgeDao

        knowledge = KnowledgeDao.query_by_id(space_id)
        if knowledge and knowledge.auto_tag_library_id:
            return int(knowledge.auto_tag_library_id)
        return 1

    @classmethod
    def _find_library_tag_in_session(
        cls,
        session,
        *,
        tenant_id: int | None,
        tag_name: str,
    ) -> Tag | None:
        normalized = (tag_name or "").strip()
        if not normalized or tenant_id is None:
            return None
        rows = session.exec(
            select(Tag).where(
                Tag.business_type == TagBusinessTypeEnum.TAG_LIBRARY.value,
                Tag.tenant_id == tenant_id,
                Tag.name == normalized,
            )
        ).all()
        return cls._pick_best_library_tag_from_rows(list(rows))

    @classmethod
    def append_file_library_tags_sync(
        cls,
        *,
        space_id: int,
        file_id: int,
        tag_names: list[str],
        user_id: int,
        tenant_id: int | None,
        resource_type: TagResourceTypeEnum,
    ) -> None:
        """Resolve tag names in ``tag`` table and link them to a space file.

        Reuses an existing tenant-wide library tag row when the name already exists.
        Otherwise inserts into the first tag library bound to ``space_id``.
        """
        normalized_names = cls._normalize_names(tag_names)
        if not normalized_names:
            return

        library_id = cls._first_library_id_for_space(space_id)
        with get_sync_db_session() as session:
            tag_by_name: dict[str, Tag] = {}
            for tag_name in normalized_names:
                if tag_name in tag_by_name:
                    continue
                existing = cls._find_library_tag_in_session(
                    session,
                    tenant_id=tenant_id,
                    tag_name=tag_name,
                )
                if existing:
                    tag_by_name[tag_name] = existing
                    continue
                if library_id is None:
                    logger.warning(
                        "skip_tag_insert_no_library space_id={} file_id={} tag_name={}",
                        space_id,
                        file_id,
                        tag_name,
                    )
                    continue
                tag = Tag(
                    name=tag_name,
                    business_type=TagBusinessTypeEnum.TAG_LIBRARY.value,
                    business_id=cls._business_id(library_id),
                    resource_type=resource_type.value,
                    user_id=user_id,
                    tenant_id=tenant_id,
                )
                session.add(tag)
                session.flush()
                tag_by_name[tag_name] = tag

            tag_ids = [tag.id for name in normalized_names if (tag := tag_by_name.get(name)) and tag.id is not None]
            if not tag_ids:
                return

            existing_links = session.exec(
                select(TagLink).where(
                    TagLink.resource_id == str(file_id),
                    TagLink.resource_type == ResourceTypeEnum.SPACE_FILE.value,
                    TagLink.tag_id.in_(tag_ids),
                )
            ).all()
            existing_tag_ids = {link.tag_id for link in existing_links}
            for tag_id in tag_ids:
                if tag_id in existing_tag_ids:
                    continue
                session.add(
                    TagLink(
                        tag_id=tag_id,
                        resource_id=str(file_id),
                        resource_type=ResourceTypeEnum.SPACE_FILE.value,
                        user_id=user_id,
                        tenant_id=tenant_id,
                    )
                )
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                logger.info(
                    "append_file_library_tags_duplicate_link_ignored space_id={} file_id={}",
                    space_id,
                    file_id,
                )
                return
        cls.invalidate_link_b_tenant_catalog_cache_sync(tenant_id)

    @classmethod
    def append_file_library_review_tags_sync(
        cls,
        *,
        space_id: int,
        file_id: int,
        tag_names: list[str],
        user_id: int,
        tenant_id: int | None,
        resource_type: TagResourceTypeEnum = TagResourceTypeEnum.AI_AUTO_TAG,
    ) -> None:
        """Create pending review tags in the first bound library and link them to a file."""
        normalized_names = cls._normalize_names(tag_names)
        if not normalized_names:
            return

        library_id = cls._first_library_id_for_space(space_id)
        if library_id is None:
            logger.warning(
                "skip_review_tag_insert_no_library space_id={} file_id={} tag_names={}",
                space_id,
                file_id,
                normalized_names,
            )
            return

        with get_sync_db_session() as session:
            tag_by_name: dict[str, ReviewTag] = {}
            for tag_name in normalized_names:
                if tag_name in tag_by_name:
                    continue

                tenant_pending = cls._find_tenant_pending_review_tag_exact_in_session(
                    session,
                    tenant_id=tenant_id,
                    tag_name=tag_name,
                    resource_type=resource_type,
                )
                if tenant_pending:
                    tag_by_name[tag_name] = tenant_pending
                    continue

                if cls._find_library_tag_in_session(session, tenant_id=tenant_id, tag_name=tag_name):
                    continue

                tag = ReviewTag(
                    name=tag_name,
                    business_type=TagBusinessTypeEnum.TAG_LIBRARY.value,
                    business_id=str(library_id),
                    resource_type=resource_type.value,
                    user_id=user_id,
                    tenant_id=tenant_id,
                )
                session.add(tag)
                session.flush()
                tag_by_name[tag_name] = tag

            tag_ids = [tag_by_name[name].id for name in normalized_names if tag_by_name.get(name)]
            if not tag_ids:
                return

            existing_links = session.exec(
                select(ReviewTagLink).where(
                    ReviewTagLink.resource_id == str(file_id),
                    ReviewTagLink.resource_type == ResourceTypeEnum.SPACE_FILE.value,
                    ReviewTagLink.tag_id.in_(tag_ids),
                )
            ).all()
            existing_tag_ids = {link.tag_id for link in existing_links}
            for tag_id in tag_ids:
                if tag_id in existing_tag_ids:
                    continue
                session.add(
                    ReviewTagLink(
                        tag_id=tag_id,
                        resource_id=str(file_id),
                        resource_type=ResourceTypeEnum.SPACE_FILE.value,
                        user_id=user_id,
                        tenant_id=tenant_id,
                    )
                )
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                logger.info(
                    "append_file_library_review_tags_duplicate_link_ignored space_id={} file_id={}",
                    space_id,
                    file_id,
                )
                return
        cls.invalidate_link_b_tenant_catalog_cache_sync(tenant_id)

    @classmethod
    async def get_or_create_library_tag_async(
        cls,
        *,
        space_id: int,
        tag_name: str,
        user_id: int,
        tenant_id: int | None,
        resource_type: TagResourceTypeEnum = TagResourceTypeEnum.MANUAL_TAG,
    ) -> Tag:
        normalized = (tag_name or "").strip()
        existing = await cls.find_library_tag_by_name(tenant_id=tenant_id, tag_name=normalized)
        if existing:
            return existing

        library_id = cls._first_library_id_for_space(space_id)
        if library_id is None:
            raise KnowledgeSpaceTagLibraryNotBoundError()

        return await TagDao.ainsert_tag(
            Tag(
                name=normalized,
                user_id=user_id,
                tenant_id=tenant_id,
                business_type=TagBusinessTypeEnum.TAG_LIBRARY.value,
                business_id=cls._business_id(library_id),
                resource_type=resource_type.value,
            )
        )

    @classmethod
    async def get_or_create_pending_review_tag_async(
        cls,
        *,
        space_id: int,
        tag_name: str,
        user_id: int,
        tenant_id: int | None,
        resource_type: TagResourceTypeEnum = TagResourceTypeEnum.MANUAL_TAG,
    ) -> ReviewTag:
        normalized = (tag_name or "").strip()
        library_id = cls._first_library_id_for_space(space_id)
        if library_id is None:
            raise KnowledgeSpaceTagLibraryNotBoundError()

        pending_tags = await ReviewTagDao.get_tags_by_business(
            TagBusinessTypeEnum.TAG_LIBRARY,
            str(library_id),
            name=normalized,
        )
        for review_tag in pending_tags:
            if (
                (review_tag.name or "").strip() == normalized
                and review_tag.review_status == 0
                and not review_tag.is_deleted
            ):
                return review_tag

        new_tag = ReviewTag(
            name=normalized,
            user_id=user_id,
            tenant_id=tenant_id,
            business_type=TagBusinessTypeEnum.TAG_LIBRARY.value,
            business_id=str(library_id),
            resource_type=resource_type.value,
            is_deleted=False,
            review_status=0,
            create_time=datetime.now(),
            update_time=datetime.now(),
        )
        return await ReviewTagDao.ainsert_review_tag(new_tag)

    @classmethod
    async def list_tenant_library_tag_name_keys(cls, tenant_id: int | None) -> set[str]:
        if tenant_id is None:
            return set()
        async with get_async_db_session() as session:
            rows = (
                await session.exec(
                    select(Tag.name).where(
                        Tag.business_type == TagBusinessTypeEnum.TAG_LIBRARY.value,
                        Tag.tenant_id == tenant_id,
                    )
                )
            ).all()
        return {str(name).strip().lower() for name in rows if name and str(name).strip()}

    @classmethod
    async def find_names_used_in_other_libraries(
        cls,
        *,
        tenant_id: int | None,
        names: Iterable[str],
        exclude_library_id: int | None = None,
    ) -> list[str]:
        """Return tag names that already exist in other tag libraries."""
        normalized = cls._normalize_names(names)
        if not normalized or tenant_id is None:
            return []

        unique_names = list(dict.fromkeys(normalized))
        exclude_business_id = cls._business_id(exclude_library_id) if exclude_library_id is not None else None

        async with get_async_db_session() as session:
            statement = select(Tag.name).where(
                Tag.business_type == TagBusinessTypeEnum.TAG_LIBRARY.value,
                Tag.tenant_id == tenant_id,
                Tag.name.in_(unique_names),
            )
            if exclude_business_id is not None:
                statement = statement.where(Tag.business_id != exclude_business_id)
            rows = (await session.exec(statement)).all()

        return list(dict.fromkeys(name for name in rows if name))

    @staticmethod
    def _resolve_new_tag_id(
        name: str,
        resource_type: str,
        new_tags: list[Tag],
    ) -> int | None:
        for tag in new_tags:
            if tag.id is not None and tag.name == name and tag.resource_type == resource_type:
                return int(tag.id)
        if resource_type in (TagResourceTypeEnum.SYSTEM_TAG.value, TagResourceTypeEnum.MANUAL_TAG.value):
            for alt_type in (TagResourceTypeEnum.SYSTEM_TAG.value, TagResourceTypeEnum.MANUAL_TAG.value):
                if alt_type == resource_type:
                    continue
                for tag in new_tags:
                    if tag.id is not None and tag.name == name and tag.resource_type == alt_type:
                        return int(tag.id)
        return None

    @classmethod
    async def _remap_tag_links_after_library_replace(
        cls,
        session,
        *,
        old_id_by_key: dict[tuple[str, str], int],
        new_tags: list[Tag],
        now: datetime,
    ) -> None:
        """Keep file tag links valid after library tag rows are recreated with new ids."""
        for (name, resource_type), old_id in old_id_by_key.items():
            new_id = cls._resolve_new_tag_id(name, resource_type, new_tags)
            if new_id is None or new_id == old_id:
                continue
            await session.exec(update(TagLink).where(TagLink.tag_id == old_id).values(tag_id=new_id, update_time=now))

    @classmethod
    async def replace_tags(
        cls,
        *,
        library_id: int,
        tenant_id: int | None,
        user_id: int,
        system_tags: Iterable[str] | None = None,
        manual_tags: Iterable[str] | None = None,
        ai_tags: Iterable[str] | None = None,
    ) -> tuple[list[str], list[str], list[str]]:
        system = cls._normalize_names(system_tags or [])
        manual = cls._normalize_names(manual_tags or [])
        ai = cls._normalize_names(ai_tags or [])
        system, manual = cls.dedupe_non_ai_tag_name_lists(system, manual)
        async with get_async_db_session() as session:
            existing = (
                await session.exec(
                    select(Tag).where(
                        Tag.business_type == TagBusinessTypeEnum.TAG_LIBRARY.value,
                        Tag.business_id == cls._business_id(library_id),
                    )
                )
            ).all()
            existing_meta = {(tag.name, tag.resource_type): (tag.create_time, tag.user_id) for tag in existing}
            old_id_by_key: dict[tuple[str, str], int] = {}
            for tag in existing:
                if tag.id is not None and tag.name:
                    old_id_by_key[(tag.name, tag.resource_type)] = int(tag.id)
            await session.exec(
                delete(Tag).where(
                    Tag.business_type == TagBusinessTypeEnum.TAG_LIBRARY.value,
                    Tag.business_id == cls._business_id(library_id),
                )
            )
            now = datetime.now()
            for name in system:
                resource_type = TagResourceTypeEnum.SYSTEM_TAG.value
                prev_create_time, prev_user_id = cls._existing_tag_meta(existing_meta, name, resource_type)
                session.add(
                    Tag(
                        name=name,
                        tenant_id=tenant_id,
                        user_id=prev_user_id or user_id,
                        business_type=TagBusinessTypeEnum.TAG_LIBRARY.value,
                        business_id=cls._business_id(library_id),
                        resource_type=resource_type,
                        create_time=prev_create_time or now,
                        update_time=now,
                    )
                )
            for name in manual:
                resource_type = TagResourceTypeEnum.MANUAL_TAG.value
                prev_create_time, prev_user_id = cls._existing_tag_meta(existing_meta, name, resource_type)
                session.add(
                    Tag(
                        name=name,
                        tenant_id=tenant_id,
                        user_id=prev_user_id or user_id,
                        business_type=TagBusinessTypeEnum.TAG_LIBRARY.value,
                        business_id=cls._business_id(library_id),
                        resource_type=resource_type,
                        create_time=prev_create_time or now,
                        update_time=now,
                    )
                )
            for name in ai:
                resource_type = TagResourceTypeEnum.AI_AUTO_TAG.value
                prev_create_time, prev_user_id = cls._existing_tag_meta(existing_meta, name, resource_type)
                session.add(
                    Tag(
                        name=name,
                        tenant_id=tenant_id,
                        user_id=prev_user_id or user_id,
                        business_type=TagBusinessTypeEnum.TAG_LIBRARY.value,
                        business_id=cls._business_id(library_id),
                        resource_type=resource_type,
                        create_time=prev_create_time or now,
                        update_time=now,
                    )
                )
            await session.flush()
            new_tags = (
                await session.exec(
                    select(Tag).where(
                        Tag.business_type == TagBusinessTypeEnum.TAG_LIBRARY.value,
                        Tag.business_id == cls._business_id(library_id),
                    )
                )
            ).all()
            await cls._remap_tag_links_after_library_replace(
                session,
                old_id_by_key=old_id_by_key,
                new_tags=new_tags,
                now=now,
            )
            await session.commit()
        await cls.invalidate_link_b_tenant_catalog_cache_async(tenant_id)
        return system, manual, ai

    @classmethod
    async def delete_for_library(cls, library_id: int) -> None:
        tenant_id: int | None = None
        async with get_async_db_session() as session:
            tenant_row = (
                await session.exec(
                    select(Tag.tenant_id)
                    .where(
                        Tag.business_type == TagBusinessTypeEnum.TAG_LIBRARY.value,
                        Tag.business_id == cls._business_id(library_id),
                    )
                    .limit(1)
                )
            ).first()
            if tenant_row is not None:
                tenant_id = int(tenant_row)
            await session.exec(
                delete(Tag).where(
                    Tag.business_type == TagBusinessTypeEnum.TAG_LIBRARY.value,
                    Tag.business_id == cls._business_id(library_id),
                )
            )
            await session.commit()
        await cls.invalidate_link_b_tenant_catalog_cache_async(tenant_id)

    @classmethod
    async def collect_space_portal_tag_map(cls, space_ids: list[int]) -> dict[str, list[Tag]]:
        """Merge legacy space-scoped tags with bound tag-library tags for portal read paths."""
        if not space_ids:
            return {}

        unique_space_ids = list(dict.fromkeys(int(space_id) for space_id in space_ids))
        tag_map: dict[str, list[Tag]] = {}

        legacy_map = await TagDao.aget_tags_by_business_ids(
            TagBusinessTypeEnum.KNOWLEDGE_SPACE,
            [str(space_id) for space_id in unique_space_ids],
        )
        for space_id in unique_space_ids:
            tag_map[str(space_id)] = list(legacy_map.get(str(space_id), []))

        library_ids_by_space: dict[int, list[int]] = {}
        all_library_ids: list[int] = []
        for space_id in unique_space_ids:
            library_ids = await KnowledgeTagLibraryLinkDao.alist_library_ids_by_knowledge(space_id)
            library_ids_by_space[space_id] = library_ids
            all_library_ids.extend(library_ids)

        unique_library_ids = list(dict.fromkeys(all_library_ids))
        if not unique_library_ids:
            return tag_map

        library_tag_map = await TagDao.aget_tags_by_business_ids(
            TagBusinessTypeEnum.TAG_LIBRARY,
            [str(library_id) for library_id in unique_library_ids],
        )
        for space_id in unique_space_ids:
            merged = list(tag_map.get(str(space_id), []))
            seen_names = {(tag.name or "").lower() for tag in merged if tag.name}
            for library_id in library_ids_by_space.get(space_id, []):
                for tag in library_tag_map.get(str(library_id), []):
                    name_key = (tag.name or "").lower()
                    if name_key and name_key not in seen_names:
                        merged.append(tag)
                        seen_names.add(name_key)
            tag_map[str(space_id)] = merged
        return tag_map

    @classmethod
    async def resolve_tag_ids_by_name_for_space(cls, space_id: int, tag_name: str) -> list[int]:
        """Resolve tag ids by name for a space (legacy knowledge_space + bound libraries)."""
        normalized = (tag_name or "").strip()
        if not normalized:
            return []

        tag_ids: list[int] = []
        legacy_tags = await TagDao.get_tags_by_business(
            TagBusinessTypeEnum.KNOWLEDGE_SPACE,
            str(space_id),
            name=normalized,
        )
        tag_ids.extend(int(tag.id) for tag in legacy_tags if tag.id is not None)

        library_ids = await KnowledgeTagLibraryLinkDao.alist_library_ids_by_knowledge(space_id)
        if library_ids:
            library_tag_map = await TagDao.aget_tags_by_business_ids(
                TagBusinessTypeEnum.TAG_LIBRARY,
                [str(library_id) for library_id in library_ids],
                name=normalized,
            )
            for tags in library_tag_map.values():
                tag_ids.extend(int(tag.id) for tag in tags if tag.id is not None)

        return list(dict.fromkeys(tag_ids))

    @staticmethod
    def _normalize_names(values: Iterable[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            name = (value or "").strip()
            if name:
                normalized.append(name)
        return normalized

    @classmethod
    async def alist_tree(cls, keyword: str) -> dict[int, list[KnowledgeSpaceTagLibraryTreeItem]]:
        tags = await TagDao.alist_tree(keyword=keyword)
        if not tags:
            return {}
        tag_map: dict[int, list[KnowledgeSpaceTagLibraryTreeItem]] = {}
        for tag in tags:
            tag_map.setdefault(tag.business_id, []).append(
                KnowledgeSpaceTagLibraryTreeItem(
                    id="T" + str(tag.id),
                    name=tag.name,
                    key=tag.id,
                    library_id=tag.business_id,
                    parent_id="L" + str(tag.business_id),
                )
            )
        return tag_map
