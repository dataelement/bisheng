"""Persist tag-library candidates in the shared ``tag`` table."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime

from sqlmodel import delete, func, select

from bisheng.core.database import get_async_db_session, get_sync_db_session
from bisheng.database.models.tag import (
    Tag,
    TagBusinessTypeEnum,
    TagDao,
    TagLink,
    TagResourceTypeEnum,
)


class TagLibraryTagService:
    @staticmethod
    def _business_id(library_id: int) -> str:
        return str(library_id)

    @classmethod
    async def list_tags(cls, library_id: int) -> list[Tag]:
        return await TagDao.get_tags_by_business(
            TagBusinessTypeEnum.TAG_LIBRARY,
            cls._business_id(library_id),
        )

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
        manual_tags: list[str] | None = None,
        ai_tags: list[str] | None = None,
    ) -> list[tuple[str, str]]:
        if tags:
            return [(tag.name or "", tag.resource_type) for tag in tags if tag.name]
        items: list[tuple[str, str]] = [
            (name, TagResourceTypeEnum.MANUAL_TAG.value) for name in (manual_tags or []) if name
        ]
        items.extend((name, TagResourceTypeEnum.AI_AUTO_TAG.value) for name in (ai_tags or []) if name)
        return items

    @classmethod
    async def _resolve_file_tag_ids(
        cls,
        *,
        items: Iterable[tuple[str, str]],
        tenant_id: int | None,
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

        async with get_async_db_session() as session:
            tag_ids = (
                await session.exec(
                    select(Tag.id).where(
                        Tag.name.in_(names),
                        Tag.tenant_id == tenant_id,
                        Tag.resource_type.in_(file_types),
                        Tag.business_type != TagBusinessTypeEnum.TAG_LIBRARY.value,
                    )
                )
            ).all()
        return [int(tag_id) for tag_id in tag_ids]

    @classmethod
    async def count_usage_batch(
        cls,
        *,
        items: Iterable[tuple[str, str]],
        tenant_id: int | None,
    ) -> dict[tuple[str, str], int]:
        """Count tag_link rows for knowledge-space file tags matching library candidates."""
        normalized_items = [(name, resource_type) for name, resource_type in items if name]
        if not normalized_items or tenant_id is None:
            return {}

        tag_ids = await cls._resolve_file_tag_ids(items=normalized_items, tenant_id=tenant_id)
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
        return await cls.count_distinct_usage_by_items(items=items, tenant_id=tenant_id)

    @classmethod
    async def count_distinct_usage_by_items(
        cls,
        *,
        items: Iterable[tuple[str, str]],
        tenant_id: int | None,
    ) -> int:
        tag_ids = await cls._resolve_file_tag_ids(items=items, tenant_id=tenant_id)
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
        manual_tags: list[str] | None = None,
        ai_tags: list[str] | None = None,
    ) -> int:
        """Sum per-tag usage counts (matches tag dialog column semantics)."""
        tags = await cls.list_tags(library_id)
        items = cls._library_usage_items(tags=tags, manual_tags=manual_tags, ai_tags=ai_tags)
        if not items or tenant_id is None:
            return 0
        usage_map = await cls.count_usage_batch(items=items, tenant_id=tenant_id)
        return sum(usage_map.values())

    @classmethod
    async def list_tag_names(
        cls,
        library_id: int,
    ) -> tuple[list[str], list[str]]:
        tags = await TagDao.get_tags_by_business(
            TagBusinessTypeEnum.TAG_LIBRARY,
            cls._business_id(library_id),
        )
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
        return manual, ai

    @classmethod
    def list_tag_names_sync(cls, library_id: int) -> tuple[list[str], list[str]]:

        statement = select(Tag).where(
            Tag.business_type == TagBusinessTypeEnum.TAG_LIBRARY.value,
            Tag.business_id == cls._business_id(library_id),
        )
        with get_sync_db_session() as session:
            tags = session.exec(statement).all()
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
        return manual, ai

    @classmethod
    async def count_tags(cls, library_id: int) -> int:
        manual, ai = await cls.list_tag_names(library_id)
        return len(manual) + len(ai)

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

    @classmethod
    async def replace_tags(
        cls,
        *,
        library_id: int,
        tenant_id: int | None,
        user_id: int,
        manual_tags: Iterable[str],
        ai_tags: Iterable[str] | None = None,
    ) -> tuple[list[str], list[str]]:
        manual = cls._normalize_names(manual_tags)
        ai = cls._normalize_names(ai_tags or [])
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
            await session.exec(
                delete(Tag).where(
                    Tag.business_type == TagBusinessTypeEnum.TAG_LIBRARY.value,
                    Tag.business_id == cls._business_id(library_id),
                )
            )
            now = datetime.now()
            for name in manual:
                resource_type = TagResourceTypeEnum.MANUAL_TAG.value
                prev_create_time, prev_user_id = existing_meta.get((name, resource_type), (None, None))
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
                prev_create_time, prev_user_id = existing_meta.get((name, resource_type), (None, None))
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
            await session.commit()
        return manual, ai

    @classmethod
    async def delete_for_library(cls, library_id: int) -> None:
        async with get_async_db_session() as session:
            await session.exec(
                delete(Tag).where(
                    Tag.business_type == TagBusinessTypeEnum.TAG_LIBRARY.value,
                    Tag.business_id == cls._business_id(library_id),
                )
            )
            await session.commit()

    @staticmethod
    def _normalize_names(values: Iterable[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            name = (value or "").strip()
            if name:
                normalized.append(name)
        return normalized
