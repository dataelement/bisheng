"""Persistence queries for a user-selected knowledge-space file tag."""

from sqlmodel import col, select

from bisheng.core.database import get_async_db_session
from bisheng.database.models.group_resource import ResourceTypeEnum
from bisheng.database.models.tag import Tag, TagBusinessTypeEnum, TagLink
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile


class KnowledgeSpaceTagRepository:
    async def tag_belongs_to_space(self, space_id: int, tag_id: int) -> bool:
        statement = select(Tag.id).where(
            Tag.id == tag_id,
            Tag.business_type == TagBusinessTypeEnum.KNOWLEDGE_SPACE,
            Tag.business_id == str(space_id),
        )
        async with get_async_db_session() as session:
            return (await session.exec(statement)).first() is not None

    async def list_tagged_file_ids(self, space_id: int, tag_id: int) -> list[int]:
        statement = select(TagLink.resource_id).where(
            TagLink.tag_id == tag_id,
            TagLink.resource_type == ResourceTypeEnum.SPACE_FILE.value,
        )
        async with get_async_db_session() as session:
            links = (await session.exec(statement)).all()
            candidates = sorted({int(value) for value in links if str(value).isdigit() and int(value) > 0})
            file_ids: set[int] = set()
            # Keep parameter counts compatible with DM8 for large tags.
            for offset in range(0, len(candidates), 500):
                files = select(KnowledgeFile.id).where(
                    KnowledgeFile.knowledge_id == space_id,
                    col(KnowledgeFile.id).in_(candidates[offset : offset + 500]),
                )
                file_ids.update(int(value) for value in (await session.exec(files)).all())
            return sorted(file_ids)
