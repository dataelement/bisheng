from datetime import datetime
from sqlmodel.ext.asyncio.session import AsyncSession
from bisheng.database.models.tag import Tag, TagLink, TagResourceTypeEnum
from bisheng.database.models.review_tags import ReviewTag, ReviewTagLink
from bisheng.knowledge.domain.models.knowledge_space_tag_library import KnowledgeSpaceTagLibrary
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from sqlmodel import select, func, update



class TagRepositoryImpl:

    def __init__(self, session: AsyncSession):
        self.session = session


    async def approve_tag_to_move(self, review_tag: ReviewTag, review_tag_link: list[ReviewTagLink]):
        tag = Tag()
        tag.name = review_tag.name
        tag.business_id = review_tag.business_id
        tag.business_type = review_tag.business_type
        tag.user_id = review_tag.user_id
        tag.tenant_id = review_tag.tenant_id
        tag.resource_type = review_tag.resource_type
        tag.create_time = review_tag.create_time
        tag.update_time = review_tag.update_time
        self.session.add(tag)
        await self.session.flush()
        for link in review_tag_link:
            taglink = TagLink()
            taglink.tag_id = tag.id
            taglink.resource_id = link.resource_id
            taglink.resource_type = link.resource_type
            taglink.tenant_id = link.tenant_id
            taglink.user_id = link.user_id
            taglink.create_time = link.create_time
            taglink.update_time = link.update_time
            self.session.add(taglink)
            await self.session.flush()


    async def get_tag_library(self, tenant_id: int):
        statement = select(KnowledgeSpaceTagLibrary).where(KnowledgeSpaceTagLibrary.tenant_id == tenant_id, KnowledgeSpaceTagLibrary.is_builtin == True)
        tag_library = await self.session.exec(statement)
        return tag_library.first()

    async def add_tag_library_by_tag(self, tag_name: str, tag_library: KnowledgeSpaceTagLibrary, resource_type: str):
        if tag_library:
            if resource_type == TagResourceTypeEnum.SYSTEM_TAG:
                tag_library.tags = [*tag_library.tags, tag_name]
                tag_library.tag_count += 1
            else:
                tag_library.ai_tags = [*tag_library.ai_tags, tag_name]
                tag_library.ai_tag_count += 1
            tag_library.update_time = datetime.now()
            self.session.add(tag_library)
            await self.session.flush()

    async def remove_tag_library_by_tag(self, tag_name: str, resource_type: TagResourceTypeEnum, tag_library: KnowledgeSpaceTagLibrary):
        if tag_library:
            if resource_type == TagResourceTypeEnum.SYSTEM_TAG:
                tag_library.tags = [t for t in tag_library.tags if t != tag_name]
                tag_library.tag_count -= 1
            else:
                tag_library.ai_tags = [t for t in tag_library.ai_tags if t != tag_name]
                tag_library.ai_tag_count -= 1
            tag_library.update_time = datetime.now()
            self.session.add(tag_library)
            await self.session.flush()

    async def update_tag_library_by_tag(self, original_tag_name: str, new_tag_name: str, tag_library: KnowledgeSpaceTagLibrary):
        if tag_library:
            tag_library.tags = [new_tag_name if t == original_tag_name else t for t in tag_library.tags]
            tag_library.update_time = datetime.now()
            self.session.add(tag_library)
            await self.session.flush()

    async def update_tag_library_by_ai_tag(self, original_tag_name: str, new_tag_name: str, tag_library: KnowledgeSpaceTagLibrary):
        if tag_library:
            tag_library.ai_tags = [new_tag_name if t == original_tag_name else t for t in tag_library.ai_tags]
            tag_library.update_time = datetime.now()
            self.session.add(tag_library)
            await self.session.flush()

    async def update_tag_by_name(self, original_tag_name: str, resource_type: TagResourceTypeEnum, tag_name: str, tenant_id: int):
        update_statement = update(Tag).where(Tag.name == original_tag_name, Tag.tenant_id == tenant_id, Tag.resource_type == resource_type).values(name=tag_name)
        return await self.session.exec(update_statement)

    async def get_tag_count_by_tag_name(self, tag_name: str, tenant_id: int):
        statement = select(func.count(Tag.id)).where(Tag.name == tag_name, Tag.tenant_id == tenant_id)
        result = await self.session.exec(statement)
        return result.one()

    async def get_tag_list_by_tag_name(self, tag_name: str, tenant_id: int):
        statement = select(Tag).where(Tag.name == tag_name, Tag.tenant_id == tenant_id)
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
            KnowledgeSpaceTagLibrary.tenant_id == tenant_id,
            KnowledgeSpaceTagLibrary.is_builtin == True
        )
        tag_library = await self.session.exec(statement)
        tag_library = tag_library.first()

        if tag_library:
            if resource_type == TagResourceTypeEnum.SYSTEM_TAG and tag_name in tag_library.tags:
                return tag_library
            elif resource_type == TagResourceTypeEnum.AI_AUTO_TAG and tag_name in tag_library.ai_tags:
                return tag_library
        return None

    async def get_knowledgefile_by_resource_id(self, resource_id: int, tenant_id: int):
        statement = select(KnowledgeFile).where(KnowledgeFile.id == resource_id, KnowledgeFile.tenant_id == tenant_id)
        knowledgefile = await self.session.exec(statement)
        return knowledgefile.first()
