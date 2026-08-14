from datetime import datetime

from sqlmodel import delete, func, select, update
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.database import get_async_db_session
from bisheng.database.models.review_tags import ReviewTag, ReviewTagLink
from bisheng.database.models.tag import Tag, TagBusinessTypeEnum, TagLink, TagResourceTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_space_tag_library import KnowledgeSpaceTagLibrary
from bisheng.knowledge.domain.services.tag_library_tag_service import TagLibraryTagService


class TagRepositoryImpl:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def approve_tag_to_move(
        self,
        review_tag: ReviewTag,
        review_tag_link: list[ReviewTagLink],
        *,
        reviewer_id: int | None = None,
        review_time: datetime | None = None,
        target_library_id: int | None = None,
    ):
        """Move an approved tag from ``review_tag`` into ``tag``.

        The approval path hard-deletes the source ``review_tag`` row afterwards,
        so the audit trail has to be stamped here — there is nothing left to read
        it back from. ``review_time`` is likewise passed in rather than copied:
        the source row is still unreviewed at this point, the service marks it
        only after the move.

        ``target_library_id`` is the library the **reviewer chose**, and it wins
        over the id recorded on the review row. That recorded id says where the
        tag was *proposed*, not where the reviewer decided it belongs; trusting
        it filed every approval into the proposing library instead.

        The approval flow registers the name into the chosen library first, which
        already leaves a row there. This updates that row rather than inserting a
        second one — two rows per approval, one holding the audit trail in the
        wrong library and one holding nothing in the right one, was the bug.
        """
        business_id = (
            TagLibraryTagService._business_id(target_library_id)
            if target_library_id is not None
            else self._resolve_approved_tag_business_id(review_tag)
        )
        tag_id, existing_links = await self.find_committed_library_tag(
            review_tag.name, business_id, review_tag.tenant_id
        )
        values = {
            # The row left by the library registration carries the reviewer as
            # its creator and "now" as its creation time; both are wrong for the
            # tag itself, so they are overwritten either way.
            "user_id": review_tag.user_id,  # the original proposer, not the reviewer
            "create_time": review_tag.create_time,
            "update_time": review_tag.update_time,
            "reviewer_id": reviewer_id,
            "review_time": review_time,
        }
        if tag_id is None:
            tag = Tag(
                name=review_tag.name,
                business_id=business_id,
                business_type=TagBusinessTypeEnum.TAG_LIBRARY.value,
                tenant_id=review_tag.tenant_id,
                # Only set on insert: an existing row's classification belongs to
                # the library, which may have filed the name differently.
                resource_type=review_tag.resource_type,
                **values,
            )
            self.session.add(tag)
            await self.session.flush()
            tag_id = tag.id
        else:
            # Updated by id rather than through a loaded object: the row was
            # committed by another connection and this transaction's snapshot
            # cannot see it, but a write always applies to the current version.
            await self.session.exec(update(Tag).where(Tag.id == tag_id).values(**values))

        for link in review_tag_link:
            # Re-approving the same file must not stack duplicate links, which
            # would inflate 已标识知识数.
            if (link.resource_id, link.resource_type) in existing_links:
                continue
            taglink = TagLink()
            taglink.tag_id = tag_id
            taglink.resource_id = link.resource_id
            taglink.resource_type = link.resource_type
            taglink.tenant_id = link.tenant_id
            taglink.user_id = link.user_id
            taglink.create_time = link.create_time
            taglink.update_time = link.update_time
            self.session.add(taglink)
            existing_links.add((link.resource_id, link.resource_type))
            await self.session.flush()

    @staticmethod
    async def find_committed_library_tag(
        name: str,
        business_id: str | None,
        tenant_id: int | None,
    ) -> tuple[int | None, set]:
        """The library's row for this name, read on a **fresh** connection.

        Registering the tag name into the library happens on its own session and
        commits there. Under MySQL's REPEATABLE READ the approving request cannot
        see that row — its snapshot was taken earlier in the request — so looking
        for it on the request's own session always came back empty and the move
        inserted a second row beside it. Reading on a new connection gets a
        snapshot that postdates the commit.

        Its existing file links come back too, and for the same reason: rebuilding
        a library remaps links onto the new row ids from that other session.
        """
        async with get_async_db_session() as session:
            row = (
                await session.exec(
                    select(Tag.id).where(
                        Tag.name == name,
                        Tag.tenant_id == tenant_id,
                        Tag.business_type == TagBusinessTypeEnum.TAG_LIBRARY.value,
                        Tag.business_id == business_id,
                    )
                )
            ).first()
            if row is None:
                return None, set()
            tag_id = int(row)
            links = (
                await session.exec(select(TagLink.resource_id, TagLink.resource_type).where(TagLink.tag_id == tag_id))
            ).all()
            return tag_id, set(links)

    async def find_library_tag_in(self, name: str, library_id: int, tenant_id: int | None) -> Tag | None:
        """By library id, for callers that do not know the encoded business_id."""
        return await self.find_library_tag(name, TagLibraryTagService._business_id(library_id), tenant_id)

    async def find_library_tag(self, name: str, business_id: str | None, tenant_id: int | None) -> Tag | None:
        statement = select(Tag).where(
            Tag.name == name,
            Tag.tenant_id == tenant_id,
            Tag.business_type == TagBusinessTypeEnum.TAG_LIBRARY.value,
            Tag.business_id == business_id,
        )
        return (await self.session.exec(statement)).first()

    @staticmethod
    def _resolve_approved_tag_business_id(review_tag: ReviewTag) -> str | None:
        business_type = review_tag.business_type
        business_id = review_tag.business_id
        if business_type == TagBusinessTypeEnum.TAG_LIBRARY.value:
            return business_id
        if business_type == TagBusinessTypeEnum.KNOWLEDGE_SPACE.value:
            space_id = (business_id or "").strip()
            if space_id.isdigit():
                library_id = TagLibraryTagService._first_library_id_for_space(int(space_id))
                if library_id is not None:
                    return TagLibraryTagService._business_id(library_id)
        return business_id

    async def get_tag_library(self, tenant_id: int):
        statement = select(KnowledgeSpaceTagLibrary).where(
            KnowledgeSpaceTagLibrary.tenant_id == tenant_id, KnowledgeSpaceTagLibrary.is_builtin == True
        )
        tag_library = await self.session.exec(statement)
        return tag_library.first()

    async def add_tag_library_by_tag(self, tag_name: str, tag_library: KnowledgeSpaceTagLibrary, resource_type: str):
        if tag_library:
            if resource_type == TagResourceTypeEnum.SYSTEM_TAG:
                tag_library.tags = [*tag_library.tags, tag_name]
                tag_library.tag_count += 1
            elif resource_type == TagResourceTypeEnum.AI_AUTO_TAG:
                tag_library.ai_tags = [*tag_library.ai_tags, tag_name]
                tag_library.ai_tag_count += 1
            tag_library.update_time = datetime.now()
            self.session.add(tag_library)
            await self.session.flush()

    async def remove_tag_library_by_tag(
        self, tag_name: str, resource_type: TagResourceTypeEnum, tag_library: KnowledgeSpaceTagLibrary
    ):
        if tag_library:
            if resource_type == TagResourceTypeEnum.SYSTEM_TAG:
                tag_library.tags = [t for t in tag_library.tags if t != tag_name]
                tag_library.tag_count -= 1
            elif resource_type == TagResourceTypeEnum.AI_AUTO_TAG:
                tag_library.ai_tags = [t for t in tag_library.ai_tags if t != tag_name]
                tag_library.ai_tag_count -= 1
            tag_library.update_time = datetime.now()
            self.session.add(tag_library)
            await self.session.flush()

    async def update_tag_library_by_tag(
        self, original_tag_name: str, new_tag_name: str, tag_library: KnowledgeSpaceTagLibrary
    ):
        if tag_library:
            tag_library.tags = [new_tag_name if t == original_tag_name else t for t in tag_library.tags]
            tag_library.update_time = datetime.now()
            self.session.add(tag_library)
            await self.session.flush()

    async def update_tag_library_by_ai_tag(
        self, original_tag_name: str, new_tag_name: str, tag_library: KnowledgeSpaceTagLibrary
    ):
        if tag_library:
            tag_library.ai_tags = [new_tag_name if t == original_tag_name else t for t in tag_library.ai_tags]
            tag_library.update_time = datetime.now()
            self.session.add(tag_library)
            await self.session.flush()

    async def update_tag_by_name(
        self, original_tag_name: str, resource_type: TagResourceTypeEnum, tag_name: str, tenant_id: int
    ):
        update_statement = (
            update(Tag)
            .where(Tag.name == original_tag_name, Tag.tenant_id == tenant_id, Tag.resource_type == resource_type)
            .values(name=tag_name)
        )
        return await self.session.exec(update_statement)

    async def get_tag_count_by_tag_name(self, tag_name: str, tenant_id: int):
        statement = select(func.count(Tag.id)).where(
            Tag.name == tag_name,
            Tag.tenant_id == tenant_id,
            Tag.resource_type.in_([TagResourceTypeEnum.SYSTEM_TAG, TagResourceTypeEnum.AI_AUTO_TAG]),
        )
        result = await self.session.exec(statement)
        return result.one()

    async def get_tag_list_by_tag_name(self, tag_name: str, resource_type: TagResourceTypeEnum, tenant_id: int):
        statement = select(Tag).where(
            Tag.name == tag_name, Tag.tenant_id == tenant_id, Tag.resource_type == resource_type
        )
        result = await self.session.exec(statement)
        return result.all()

    async def get_tag_link_count_by_tag_id(self, tag_ids: list[int], tenant_id: int):
        statement = select(func.count(TagLink.id)).where(TagLink.tag_id.in_(tag_ids), TagLink.tenant_id == tenant_id)
        result = await self.session.exec(statement)
        return result.one()

    async def get_all_library_list(self, tag_library: KnowledgeSpaceTagLibrary):
        tags_list = tag_library.tags or []
        ai_tags_list = tag_library.ai_tags or []
        return tags_list + ai_tags_list

    async def get_tag_library_by_tag_name(self, tag_name: str, resource_type: TagResourceTypeEnum, tenant_id: int):
        statement = select(KnowledgeSpaceTagLibrary).where(
            KnowledgeSpaceTagLibrary.tenant_id == tenant_id, KnowledgeSpaceTagLibrary.is_builtin == True
        )
        tag_library = await self.session.exec(statement)
        tag_library = tag_library.first()

        if tag_library:
            if resource_type == TagResourceTypeEnum.SYSTEM_TAG and tag_name in tag_library.tags:
                return tag_library
            elif resource_type == TagResourceTypeEnum.AI_AUTO_TAG and tag_name in tag_library.ai_tags:
                return tag_library
        return None

    async def get_knowledgefile_by_resource_id(self, resource_id: int | str, tenant_id: int):
        normalized_resource_id = int(resource_id)
        statement = select(KnowledgeFile).where(
            KnowledgeFile.id == normalized_resource_id,
            KnowledgeFile.tenant_id == tenant_id,
        )
        knowledgefile = await self.session.exec(statement)
        return knowledgefile.first()

    async def list_all_tags_by_page(self, page: int, page_size: int, keyword: str, tenant_id: int):
        stmt = select(Tag.name, Tag.resource_type).where(Tag.tenant_id == tenant_id)
        if keyword:
            stmt = stmt.where(Tag.name.like(f"%{keyword}%"))
        stmt = (
            stmt.group_by(Tag.name, Tag.resource_type)
            .order_by(Tag.name, Tag.resource_type)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.session.exec(stmt)
        rows = result.all()
        return [{"name": row.name, "resource_type": row.resource_type} for row in rows]

    async def get_all_tag_library_count_by_page(self, keyword: str, tenant_id: int):
        subq = select(1).select_from(Tag).where(Tag.tenant_id == tenant_id)
        if keyword:
            subq = subq.where(Tag.name.like(f"%{keyword}%"))
        subq = subq.group_by(Tag.name, Tag.resource_type)
        stmt = select(func.count()).select_from(subq.subquery())
        result = await self.session.exec(stmt)
        count = result.first()
        if count is None:
            return 0
        if isinstance(count, int):
            return count
        return int(count[0])

    async def delete_tag_library_by_name(self, tag_name: str, resource_type: TagResourceTypeEnum, tenant_id: int):
        delete_statement = delete(Tag).where(
            Tag.name == tag_name, Tag.tenant_id == tenant_id, Tag.resource_type == resource_type
        )
        return await self.session.exec(delete_statement)

    async def query_existed_tag_by_review_tag(self, review_tag: ReviewTag):
        stmt = select(Tag).where(
            Tag.name == review_tag.name,
            Tag.tenant_id == review_tag.tenant_id,
            Tag.business_type == review_tag.business_type,
            Tag.business_id == review_tag.business_id,
        )
        result = await self.session.exec(stmt)
        return result.first()
