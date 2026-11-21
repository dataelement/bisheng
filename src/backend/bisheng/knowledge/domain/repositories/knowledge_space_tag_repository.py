"""Persistence queries for a user-selected knowledge-space file tag."""

from sqlalchemy import delete
from sqlmodel import col, select

from bisheng.common.errcode.knowledge import KnowledgeTagNotExistError
from bisheng.common.errcode.knowledge_space import SpaceFileNotFoundError
from bisheng.core.context.tenant import get_current_tenant_id, strict_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.database.models.group_resource import ResourceTypeEnum
from bisheng.database.models.tag import Tag, TagBusinessTypeEnum, TagLink
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile


class KnowledgeSpaceTagRepository:
    async def tag_belongs_to_space(self, space_id: int, tag_id: int) -> bool:
        statement = select(Tag.id).where(
            Tag.id == tag_id,
            Tag.tenant_id == get_current_tenant_id(),
            Tag.business_type.in_((TagBusinessTypeEnum.KNOWLEDGE_SPACE, TagBusinessTypeEnum.KNOWLEDGE)),
            Tag.business_id == str(space_id),
        )
        async with get_async_db_session() as session:
            return (await session.exec(statement)).first() is not None

    async def list_tagged_file_ids(self, space_id: int, tag_id: int) -> list[int]:
        statement = select(TagLink.resource_id).where(
            TagLink.tag_id == tag_id,
            TagLink.tenant_id == get_current_tenant_id(),
            TagLink.resource_type.in_((ResourceTypeEnum.SPACE_FILE.value, ResourceTypeEnum.KNOWLEDGE_FILE.value)),
        )
        async with get_async_db_session() as session:
            links = (await session.exec(statement)).all()
            candidates = sorted({int(value) for value in links if str(value).isdigit() and int(value) > 0})
            file_ids: set[int] = set()
            # Keep parameter counts compatible with DM8 for large tags.
            for offset in range(0, len(candidates), 500):
                files = select(KnowledgeFile.id).where(
                    KnowledgeFile.knowledge_id == space_id,
                    KnowledgeFile.tenant_id == get_current_tenant_id(),
                    col(KnowledgeFile.id).in_(candidates[offset : offset + 500]),
                )
                file_ids.update(int(value) for value in (await session.exec(files)).all())
            return sorted(file_ids)

    async def list_space_tags(self, space_id: int, *, name: str | None = None) -> list[Tag]:
        statement = select(Tag).where(
            Tag.tenant_id == get_current_tenant_id(),
            Tag.business_id == str(space_id),
            Tag.business_type.in_((TagBusinessTypeEnum.KNOWLEDGE_SPACE, TagBusinessTypeEnum.KNOWLEDGE)),
        )
        if name is not None:
            statement = statement.where(Tag.name == name)
        async with get_async_db_session() as session:
            return list((await session.exec(statement.order_by(Tag.id))).all())

    async def delete_space_tag(self, space_id: int, tag_id: int) -> bool:
        tenant = get_current_tenant_id()
        if type(tenant) is not int or tenant <= 0:
            raise KnowledgeTagNotExistError()
        async with get_async_db_session() as session:
            tag = (
                await session.exec(
                    select(Tag)
                    .where(
                        Tag.id == tag_id,
                        Tag.tenant_id == tenant,
                        Tag.business_id == str(space_id),
                        Tag.business_type.in_((TagBusinessTypeEnum.KNOWLEDGE_SPACE, TagBusinessTypeEnum.KNOWLEDGE)),
                    )
                    .with_for_update()
                )
            ).one_or_none()
            if tag is None:
                raise KnowledgeTagNotExistError()
            await session.execute(delete(TagLink).where(TagLink.tenant_id == tenant, TagLink.tag_id == tag_id))
            await session.delete(tag)
            await session.commit()
        return True

    async def replace_file_tags(self, space_id, file_id, tag_ids, *, user_id):
        """Normalize legacy file-tag links in one owned transaction."""
        tenant = get_current_tenant_id()
        if type(tenant) is not int or tenant <= 0:
            raise SpaceFileNotFoundError()
        ids = sorted(set(tag_ids))
        async with get_async_db_session() as session:
            with strict_tenant_filter():
                file = (
                    await session.exec(
                        select(KnowledgeFile)
                        .where(
                            KnowledgeFile.id == file_id,
                            KnowledgeFile.tenant_id == tenant,
                            KnowledgeFile.knowledge_id == space_id,
                            KnowledgeFile.file_type == 1,
                        )
                        .with_for_update()
                    )
                ).one_or_none()
                if file is None or file.tenant_id != tenant:
                    raise SpaceFileNotFoundError()
                if ids:
                    actual = (
                        await session.exec(
                            select(Tag.id)
                            .where(
                                col(Tag.id).in_(ids),
                                Tag.tenant_id == tenant,
                                Tag.business_id == str(space_id),
                                Tag.business_type.in_(
                                    (TagBusinessTypeEnum.KNOWLEDGE_SPACE, TagBusinessTypeEnum.KNOWLEDGE)
                                ),
                            )
                            .with_for_update()
                        )
                    ).all()
                    if set(actual) != set(ids):
                        raise KnowledgeTagNotExistError()
                await session.execute(
                    delete(TagLink).where(
                        TagLink.tenant_id == tenant,
                        TagLink.resource_id == str(file_id),
                        TagLink.resource_type.in_(
                            (ResourceTypeEnum.SPACE_FILE.value, ResourceTypeEnum.KNOWLEDGE_FILE.value)
                        ),
                    )
                )
                session.add_all(
                    [
                        TagLink(
                            tag_id=ident,
                            resource_id=str(file_id),
                            resource_type=ResourceTypeEnum.SPACE_FILE.value,
                            tenant_id=tenant,
                            user_id=user_id,
                        )
                        for ident in ids
                    ]
                )
                await session.commit()
