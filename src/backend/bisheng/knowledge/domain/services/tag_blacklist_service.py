"""Tenant tag blacklist: reject auto-insert, search, and AI-candidate filtering."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from bisheng.common.errcode.tag import (
    TagBlacklistAlreadyExistError,
    TagBlacklistLimitExceededError,
    TagBlacklistNotFoundError,
    TagNameParamsIsEmptyError,
)
from bisheng.knowledge.domain.models.tag_blacklist import TagBlacklist, TagBlacklistDao
from bisheng.knowledge.domain.services.tag_library_tag_service import (
    PENDING_REVIEW_TAG_SIMILARITY_THRESHOLD,
    TagLibraryTagService,
)

TAG_BLACKLIST_MAX = 1000


@dataclass(frozen=True)
class TagBlacklistPreview:
    count: int
    limit: int
    new_count: int
    would_exceed: bool


class TagBlacklistService:
    @staticmethod
    def normalize_name_key(name: str) -> str:
        return TagLibraryTagService.normalize_tag_name_key(name)

    @classmethod
    def _unique_names(cls, names: Sequence[str]) -> list[tuple[str, str]]:
        unique: list[tuple[str, str]] = []
        seen: set[str] = set()
        for raw in names:
            name = str(raw or "").strip()
            key = cls.normalize_name_key(name)
            if not key or key in seen:
                continue
            seen.add(key)
            unique.append((name, key))
        return unique

    @classmethod
    async def preview_insert_async(cls, names: Sequence[str]) -> TagBlacklistPreview:
        unique = cls._unique_names(names)
        count = await TagBlacklistDao.acount()
        existing = await TagBlacklistDao.alist_existing_name_keys([key for _, key in unique])
        new_count = sum(1 for _, key in unique if key not in existing)
        return TagBlacklistPreview(
            count=count,
            limit=TAG_BLACKLIST_MAX,
            new_count=new_count,
            would_exceed=count + new_count > TAG_BLACKLIST_MAX,
        )

    @classmethod
    def preview_insert_sync(cls, names: Sequence[str]) -> TagBlacklistPreview:
        unique = cls._unique_names(names)
        count = TagBlacklistDao.count_sync()
        existing = TagBlacklistDao.list_existing_name_keys_sync([key for _, key in unique])
        new_count = sum(1 for _, key in unique if key not in existing)
        return TagBlacklistPreview(
            count=count,
            limit=TAG_BLACKLIST_MAX,
            new_count=new_count,
            would_exceed=count + new_count > TAG_BLACKLIST_MAX,
        )

    @classmethod
    async def ensure_can_insert_async(cls, names: Sequence[str]) -> TagBlacklistPreview:
        preview = await cls.preview_insert_async(names)
        if preview.would_exceed:
            raise TagBlacklistLimitExceededError(
                count=preview.count,
                limit=preview.limit,
                new_count=preview.new_count,
            )
        return preview

    @classmethod
    async def add_names_async(cls, names: Sequence[str], user_id: int) -> int:
        unique = cls._unique_names(names)
        if not unique:
            return 0
        existing = await TagBlacklistDao.alist_existing_name_keys([key for _, key in unique])
        remaining = max(0, TAG_BLACKLIST_MAX - await TagBlacklistDao.acount())
        inserted = 0
        for name, key in unique:
            if key in existing:
                continue
            if inserted >= remaining:
                break
            row = await TagBlacklistDao.aadd(name=name, name_key=key, user_id=user_id)
            if row is not None:
                inserted += 1
        return inserted

    @classmethod
    async def add_name_async(cls, name: str, user_id: int) -> TagBlacklist:
        unique = cls._unique_names([name])
        if not unique:
            raise TagNameParamsIsEmptyError()
        display, key = unique[0]
        existing = await TagBlacklistDao.alist_existing_name_keys([key])
        if key in existing:
            raise TagBlacklistAlreadyExistError()
        await cls.ensure_can_insert_async([display])
        row = await TagBlacklistDao.aadd(name=display, name_key=key, user_id=user_id)
        if row is None:
            raise TagBlacklistAlreadyExistError()
        return row

    @classmethod
    def list_catalog_entries_sync(cls) -> list[tuple[str, str]]:
        return TagBlacklistDao.list_catalog_entries_sync()

    @classmethod
    def is_blocked_name(
        cls,
        name: str,
        catalog: Sequence[tuple[str, str]] | None = None,
        *,
        similarity_threshold: float = PENDING_REVIEW_TAG_SIMILARITY_THRESHOLD,
    ) -> bool:
        entries = list(catalog) if catalog is not None else cls.list_catalog_entries_sync()
        if not entries:
            return False
        _, match_kind, _ = TagLibraryTagService.find_similar_tag_name(
            name,
            entries,
            similarity_threshold=similarity_threshold,
            allow_substring=True,
        )
        return match_kind != "new"

    @classmethod
    def filter_unblocked_names(
        cls,
        names: Sequence[str],
        catalog: Sequence[tuple[str, str]] | None = None,
        *,
        similarity_threshold: float = PENDING_REVIEW_TAG_SIMILARITY_THRESHOLD,
    ) -> list[str]:
        entries = list(catalog) if catalog is not None else cls.list_catalog_entries_sync()
        if not entries:
            return [str(name).strip() for name in names if str(name or "").strip()]
        kept: list[str] = []
        seen: set[str] = set()
        for raw in names:
            name = str(raw or "").strip()
            if not name:
                continue
            key = cls.normalize_name_key(name)
            if key in seen:
                continue
            if cls.is_blocked_name(name, entries, similarity_threshold=similarity_threshold):
                continue
            seen.add(key)
            kept.append(name)
        return kept

    @classmethod
    async def search_async(
        cls,
        *,
        keyword: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[TagBlacklist], int, int]:
        offset = (page - 1) * page_size
        rows, total = await TagBlacklistDao.asearch(keyword=keyword, offset=offset, limit=page_size)
        count = await TagBlacklistDao.acount()
        return rows, total, count

    @classmethod
    async def delete_async(cls, blacklist_id: int) -> None:
        row = await TagBlacklistDao.aget(blacklist_id)
        if row is None:
            raise TagBlacklistNotFoundError()
        await TagBlacklistDao.adelete(blacklist_id)
