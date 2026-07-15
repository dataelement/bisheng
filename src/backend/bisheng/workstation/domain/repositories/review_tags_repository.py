from datetime import datetime

from sqlalchemy import delete, func, select, update
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.tag import (
    NewTagExistedError,
    OriginalTagNotFoundError,
    TagLibraryNotFoundError,
    TargetTagInUsedError,
)
from bisheng.core.storage.minio.minio_manager import get_minio_storage
from bisheng.database.models.review_tags import ApproveOrRejectEnum, ReviewTag, ReviewTagLink
from bisheng.database.models.tag import Tag, TagBusinessTypeEnum, TagResourceTypeEnum
from bisheng.workstation.domain.repositories.tags_repository import TagRepositoryImpl
from bisheng.workstation.domain.schemas.review_tags_schema import ReviewTagSubmitterTarget


class ReviewTagsRepositoryImpl:
    """ReviewTag Base Repository Class"""

    def __init__(self, session: AsyncSession, tags_repository: TagRepositoryImpl):
        self.session = session
        self.tags_repository = tags_repository

    async def delete_review_tag_link(self, tag_id: int, tenant_id: int):
        await self.session.exec(
            update(ReviewTagLink)
            .where(ReviewTagLink.tag_id == tag_id, ReviewTagLink.tenant_id == tenant_id)
            .values(is_deleted=True, update_time=datetime.now())
        )

    async def delete_review_tag_id(
        self, tag_id: int, business_type: str, resource_type: TagResourceTypeEnum, tenant_id: int
    ):
        await self.session.exec(
            update(ReviewTag)
            .where(
                ReviewTag.id == tag_id,
                ReviewTag.business_type == business_type,
                ReviewTag.resource_type == resource_type,
                ReviewTag.tenant_id == tenant_id,
            )
            .values(is_deleted=True, update_time=datetime.now())
        )
        await self.delete_review_tag_link(tag_id, tenant_id)

    async def approve_review_tag(self, tag_name: str, resource_type: TagResourceTypeEnum, tenant_id: int):
        await self.session.exec(
            delete(ReviewTagLink).where(
                ReviewTagLink.tag_id.in_(
                    select(ReviewTag.id).where(
                        ReviewTag.name == tag_name,
                        ReviewTag.tenant_id == tenant_id,
                        ReviewTag.resource_type == resource_type,
                        ReviewTag.is_deleted == False,
                    )
                ),
                ReviewTagLink.tenant_id == tenant_id,
            )
        )
        await self.session.exec(
            delete(ReviewTag).where(
                ReviewTag.name == tag_name,
                ReviewTag.tenant_id == tenant_id,
                ReviewTag.resource_type == resource_type,
                ReviewTag.is_deleted == False,
            )
        )

    async def reject_review_tag(
        self, tag_name: str, reject_reason: str, resource_type: TagResourceTypeEnum, tenant_id: int
    ):
        await self.session.exec(
            update(ReviewTag)
            .where(
                ReviewTag.name == tag_name, ReviewTag.tenant_id == tenant_id, ReviewTag.resource_type == resource_type
            )
            .values(
                is_deleted=True,
                reject_reason=reject_reason,
                update_time=datetime.now(),
                review_status=ApproveOrRejectEnum.REJECT.value,
                review_time=datetime.now(),
            )
        )
        await self.delete_review_tag_link_jilian(tag_name, resource_type, tenant_id)

    async def delete_review_tag_link_jilian(self, tag_name: str, resource_type: TagResourceTypeEnum, tenant_id: int):
        await self.session.exec(
            update(ReviewTagLink)
            .where(
                ReviewTagLink.tag_id.in_(
                    select(ReviewTag.id).where(
                        ReviewTag.name == tag_name,
                        ReviewTag.tenant_id == tenant_id,
                        ReviewTag.resource_type == resource_type,
                    )
                ),
                ReviewTagLink.tenant_id == tenant_id,
            )
            .values(is_deleted=True, update_time=datetime.now())
        )

    async def get_review_tag_by_tag_id(self, tag_id: int, tenant_id: int):
        statement = select(ReviewTag).where(
            ReviewTag.id == tag_id, ReviewTag.tenant_id == tenant_id, ReviewTag.is_deleted == False
        )
        review_tag = await self.session.exec(statement)
        return review_tag.first()

    async def query_review_tag_link_list_by_tag_id(self, tag_id: int, tenant_id: int):
        statement = select(ReviewTagLink).where(
            ReviewTagLink.tag_id == tag_id, ReviewTagLink.tenant_id == tenant_id, ReviewTagLink.is_deleted == False
        )
        review_tag_link = await self.session.exec(statement)
        return review_tag_link.scalars().all()

    async def approve_tag_to_move(
        self,
        review_tag: ReviewTag,
        review_tag_link: list[ReviewTagLink],
        *,
        skip_library_add: bool = False,
    ):
        if not skip_library_add:
            if (
                review_tag.resource_type == TagResourceTypeEnum.SYSTEM_TAG
                or review_tag.resource_type == TagResourceTypeEnum.AI_AUTO_TAG
            ):
                await self.create_tag_library_by_tag(review_tag.name, review_tag.tenant_id, review_tag.resource_type)
        await self.tags_repository.approve_tag_to_move(review_tag, review_tag_link)

    async def create_tag_library_by_tag(self, tag_name: str, tenant_id: int, resource_type: TagResourceTypeEnum):
        tag_library = await self.tags_repository.get_tag_library(tenant_id)
        if tag_library:
            tags_list = await self.tags_repository.get_all_library_list(tag_library)
            if tag_name not in tags_list:
                await self.tags_repository.add_tag_library_by_tag(tag_name, tag_library, resource_type)
        else:
            raise TagLibraryNotFoundError.http_exception()

    async def update_tag_library_by_tag(
        self, original_tag_name: str, tag_name: str, resource_type: TagResourceTypeEnum, tenant_id: int
    ):
        tag_library = await self.tags_repository.get_tag_library(tenant_id)
        if tag_library:
            tags = tag_library.tags or []
            ai_tags = tag_library.ai_tags or []
            if tag_name in ai_tags and tag_name in tags:
                raise NewTagExistedError.http_exception()
            if original_tag_name not in tags and original_tag_name not in ai_tags:
                raise OriginalTagNotFoundError.http_exception()
            if resource_type == TagResourceTypeEnum.SYSTEM_TAG:
                await self.tags_repository.update_tag_library_by_tag(original_tag_name, tag_name, tag_library)
            elif resource_type == TagResourceTypeEnum.AI_AUTO_TAG:
                await self.tags_repository.update_tag_library_by_ai_tag(original_tag_name, tag_name, tag_library)
            await self.tags_repository.update_tag_by_name(original_tag_name, resource_type, tag_name, tenant_id)
        else:
            raise TagLibraryNotFoundError.http_exception()

    async def update_tag_library_by_manual_tag(
        self, original_tag_name: str, tag_name: str, resource_type: TagResourceTypeEnum, tenant_id: int
    ):
        await self.tags_repository.update_tag_by_name(original_tag_name, resource_type, tag_name, tenant_id)

    async def delete_tag_library_by_tag(self, tag_name: str, resource_type: TagResourceTypeEnum, tenant_id: int):
        tag_library = await self.tags_repository.get_tag_library(tenant_id)
        if tag_library:
            if tag_name in (tag_library.tags or []) or tag_name in (tag_library.ai_tags or []):
                # 检查是否有其他标签使用该标签库
                tag_count = await self.tags_repository.get_tag_count_by_tag_name(tag_name, tenant_id)
                if tag_count > 0:
                    raise TargetTagInUsedError.http_exception()
                await self.tags_repository.remove_tag_library_by_tag(tag_name, resource_type, tag_library)
            else:
                raise OriginalTagNotFoundError.http_exception()
        else:
            raise TagLibraryNotFoundError.http_exception()

    async def get_list_tag_library_by_name(self, keyword: str, tenant_id: int):
        tag_library = await self.tags_repository.get_tag_library(tenant_id)
        if tag_library:
            tags = tag_library.tags or []
            ai_tags = tag_library.ai_tags or []
            result = dict.fromkeys(tags, TagResourceTypeEnum.SYSTEM_TAG) | dict.fromkeys(
                ai_tags, TagResourceTypeEnum.AI_AUTO_TAG
            )

            all_tags_list = await self.tags_repository.get_all_library_list(tag_library)
            if keyword:
                tags_list = []
                for tag in all_tags_list:
                    if keyword in tag:
                        tags_list.append(tag)
                return tags_list, result
            else:
                return all_tags_list, result
        else:
            return [], {}

    async def get_list_tag_library_by_name(self, keyword: str, tenant_id: int):
        tag_library = await self.tags_repository.get_tag_library(tenant_id)
        if tag_library:
            tags = tag_library.tags or []
            ai_tags = tag_library.ai_tags or []
            result = dict.fromkeys(tags, TagResourceTypeEnum.SYSTEM_TAG)

            all_tags_list = await self.tags_repository.get_all_library_list(tag_library)
            if keyword:
                tags_list = []
                for tag in all_tags_list:
                    if keyword in tag:
                        tags_list.append(tag)
                return tags_list, result
            else:
                return all_tags_list, result
        else:
            return [], {}

    async def get_tag_info_by_tag(self, tag_name: str, resource_type: TagResourceTypeEnum, tenant_id: int):
        tag_list = await self.tags_repository.get_tag_list_by_tag_name(tag_name, resource_type, tenant_id)
        tags_count = 0
        if tag_list and len(tag_list) > 0:
            ids = [tag.id for tag in tag_list]
            tags_count = await self.tags_repository.get_tag_link_count_by_tag_id(ids, tenant_id)
        return {"tag_name": tag_name, "resource_type": resource_type, "resource_count": tags_count}

    async def get_not_exist_tag_info_by_tag(self, tag_name: str, resource_type: TagResourceTypeEnum, tenant_id: int):
        tag_list = await self.tags_repository.get_tag_list_by_tag_name(tag_name, resource_type, tenant_id)
        if not tag_list or len(tag_list) == 0:
            return {"tag_name": tag_name, "resource_type": resource_type, "resource_count": 0}
        return None

    @staticmethod
    def _library_tag_name_subquery(tenant_id: int):
        return select(Tag.name).where(
            Tag.business_type == TagBusinessTypeEnum.TAG_LIBRARY.value,
            Tag.tenant_id == tenant_id,
        )

    async def get_review_tag_group_list_by_page(self, page: int, page_size: int, tenant_id: int, keyword: str = ""):
        where_clause = [
            ReviewTag.tenant_id == tenant_id,
            ReviewTag.is_deleted == False,
            ReviewTag.review_status == 0,
            ReviewTag.name.not_in(self._library_tag_name_subquery(tenant_id)),
        ]
        if keyword:
            where_clause.append(ReviewTag.name.like(f"%{keyword}%"))

        # 分页数据
        stmt = (
            select(ReviewTag.name, ReviewTag.resource_type)
            .where(*where_clause)
            .group_by(ReviewTag.name, ReviewTag.resource_type)
            .order_by(ReviewTag.name, ReviewTag.resource_type)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.session.exec(stmt)
        rows = result.all()
        return [{"name": row.name, "resource_type": row.resource_type} for row in rows]

    async def get_review_tag_group_count_by_page(self, tenant_id: int, keyword: str = ""):
        where_clause = [
            ReviewTag.tenant_id == tenant_id,
            ReviewTag.is_deleted == False,
            ReviewTag.review_status == 0,
            ReviewTag.name.not_in(self._library_tag_name_subquery(tenant_id)),
        ]
        if keyword:
            where_clause.append(ReviewTag.name.like(f"%{keyword}%"))
        subq = select(1).select_from(ReviewTag).where(*where_clause).group_by(ReviewTag.name, ReviewTag.resource_type)
        stmt = select(func.count()).select_from(subq.subquery())
        result = await self.session.exec(stmt)
        count = result.first()
        if count is None:
            return 0
        if isinstance(count, int):
            return count
        return int(count[0])

    @staticmethod
    def _resolve_review_tag_library_id(tag_list: list) -> int | None:
        from bisheng.database.models.tag import TagBusinessTypeEnum

        for tag in tag_list or []:
            if tag.business_type != TagBusinessTypeEnum.TAG_LIBRARY.value:
                continue
            business_id = str(getattr(tag, "business_id", "") or "").strip()
            if not business_id.isdigit():
                continue
            return int(business_id)
        return None

    async def get_review_tag_resource_info_by_tag(
        self, group_tag_name: str, resource_type: TagResourceTypeEnum, tenant_id: int
    ):
        tag_list = await self.get_review_tag_list_by_tag_name(group_tag_name, resource_type, tenant_id)
        tag_library_id = self._resolve_review_tag_library_id(tag_list)
        knowledge_ids = list(
            dict.fromkeys(
                int(tag.business_id)
                for tag in (tag_list or [])
                if tag.business_type == TagBusinessTypeEnum.KNOWLEDGE_SPACE.value
                and tag.business_id is not None
                and str(tag.business_id).isdigit()
            )
        )
        if tag_list and len(tag_list) > 0:
            minio_client = await get_minio_storage()
            resource_list = []
            ids = [tag.id for tag in tag_list]
            review_tag_link_list = await self.get_review_tag_link_list_by_tag_id(ids, tenant_id)
            if review_tag_link_list and len(review_tag_link_list) > 0:
                for tag_link in review_tag_link_list:
                    file_info = {}
                    knowledgefile = await self.tags_repository.get_knowledgefile_by_resource_id(
                        tag_link.resource_id, tenant_id
                    )
                    if knowledgefile:
                        if knowledgefile.object_name:
                            file_url = await minio_client.get_share_link(
                                knowledgefile.object_name,
                                minio_client.bucket,
                                clear_host=False,
                            )
                        else:
                            file_url = ""
                        file_info["file_url"] = file_url
                        file_info["file_name"] = knowledgefile.file_name
                        file_info["file_size"] = knowledgefile.file_size
                        file_info["file_type"] = knowledgefile.file_type
                        file_info["file_source"] = knowledgefile.file_source
                        file_info["thumbnails"] = knowledgefile.thumbnails
                        file_info["abstract"] = knowledgefile.abstract
                        file_info["level"] = knowledgefile.level
                        file_info["file_level_path"] = knowledgefile.file_level_path
                        file_info["id"] = knowledgefile.id
                        file_info["knowledge_id"] = knowledgefile.knowledge_id
                        file_info["submit_time"] = (
                            tag_link.create_time.strftime("%Y-%m-%d %H:%M:%S") if tag_link.create_time else ""
                        )
                    if file_info:
                        resource_list.append(file_info)
                return {
                    "tag_name": group_tag_name,
                    "resource_type": resource_type,
                    "tags_count": len(tag_list),
                    "resource_files": resource_list or [],
                    "knowledge_ids": knowledge_ids,
                    "tag_library_id": tag_library_id,
                }

        return {
            "tag_name": group_tag_name,
            "resource_type": resource_type,
            "tags_count": len(tag_list or []),
            "resource_files": [],
            "knowledge_ids": knowledge_ids,
            "tag_library_id": tag_library_id,
        }

    async def get_review_tag_link_list_by_tag_id(self, tag_ids: list[int], tenant_id: int):
        statement = select(ReviewTagLink).where(
            ReviewTagLink.tag_id.in_(tag_ids), ReviewTagLink.tenant_id == tenant_id, ReviewTagLink.is_deleted == False
        )
        review_tag_link_list = await self.session.exec(statement)
        return review_tag_link_list.scalars().all()

    async def get_review_tag_list_by_tag_name(self, tag_name: str, resource_type: TagResourceTypeEnum, tenant_id: int):
        statement = select(ReviewTag).where(
            ReviewTag.name == tag_name,
            ReviewTag.tenant_id == tenant_id,
            ReviewTag.is_deleted == False,
            ReviewTag.review_status == 0,
            ReviewTag.resource_type == resource_type,
        )
        review_tag_list = await self.session.exec(statement)
        return review_tag_list.scalars().all()

    @staticmethod
    def _parse_knowledge_space_id(business_id: str | None) -> int | None:
        normalized = (business_id or "").strip()
        if normalized.isdigit():
            return int(normalized)
        return None

    @classmethod
    def _space_id_from_review_tag(cls, tag) -> int | None:
        business_type = str(getattr(tag, "business_type", "") or "")
        business_id = getattr(tag, "business_id", None)
        if business_type in (
            TagBusinessTypeEnum.KNOWLEDGE_SPACE.value,
            TagBusinessTypeEnum.KNOWLEDGE.value,
        ):
            return cls._parse_knowledge_space_id(business_id)
        return None

    async def _resolve_space_id_from_tag_links(self, tag_id: int, tenant_id: int) -> int | None:
        links = await self.get_review_tag_link_list_by_tag_id([tag_id], tenant_id)
        for link in links or []:
            knowledgefile = await self.tags_repository.get_knowledgefile_by_resource_id(
                link.resource_id,
                tenant_id,
            )
            if knowledgefile and knowledgefile.knowledge_id:
                return int(knowledgefile.knowledge_id)
        return None

    async def _resolve_file_target_from_link(
        self,
        link,
        tenant_id: int,
    ) -> tuple[int | None, int | None, str | None, str | None]:
        knowledgefile = await self.tags_repository.get_knowledgefile_by_resource_id(
            link.resource_id,
            tenant_id,
        )
        if not knowledgefile or knowledgefile.id is None:
            return None, None, None, None
        space_id = int(knowledgefile.knowledge_id) if knowledgefile.knowledge_id else None
        file_id = int(knowledgefile.id)
        file_name = knowledgefile.file_name
        file_type = knowledgefile.file_type
        return space_id, file_id, file_name, file_type

    async def _resolve_primary_file_for_tag(
        self,
        tag_id: int,
        user_id: int,
        tenant_id: int,
    ) -> tuple[int | None, int | None, str | None, str | None]:
        links = await self.get_review_tag_link_list_by_tag_id([tag_id], tenant_id)
        preferred = next((link for link in links or [] if int(link.user_id or 0) == user_id), None)
        chosen = preferred or ((links or [None])[0])
        if chosen is None:
            return None, None, None, None
        return await self._resolve_file_target_from_link(chosen, tenant_id)

    async def list_submitter_notification_targets(
        self,
        tag_name: str,
        resource_type: TagResourceTypeEnum,
        tenant_id: int,
        *,
        exclude_user_id: int | None = None,
    ) -> list[ReviewTagSubmitterTarget]:
        """Return unique submitters with their related knowledge space and file."""
        tags = await self.get_review_tag_list_by_tag_name(tag_name, resource_type, tenant_id)
        user_targets: dict[int, ReviewTagSubmitterTarget] = {}

        for tag in tags:
            user_id = int(tag.user_id or 0)
            if user_id <= 0:
                continue
            space_id = self._space_id_from_review_tag(tag)
            file_id: int | None = None
            file_name: str | None = None
            file_type: str | None = None
            if tag.id is not None:
                resolved_space, resolved_file, resolved_name, resolved_type = await self._resolve_primary_file_for_tag(
                    int(tag.id),
                    user_id,
                    tenant_id,
                )
                if space_id is None:
                    space_id = resolved_space
                file_id = resolved_file
                file_name = resolved_name
                file_type = resolved_type
            existing = user_targets.get(user_id)
            if existing is None or (existing.knowledge_space_id is None and space_id is not None):
                user_targets[user_id] = ReviewTagSubmitterTarget(
                    user_id=user_id,
                    knowledge_space_id=space_id,
                    file_id=file_id,
                    file_name=file_name,
                    file_type=file_type,
                )

        tag_ids = [int(tag.id) for tag in tags if tag.id is not None]
        if tag_ids:
            tag_by_id = {int(tag.id): tag for tag in tags if tag.id is not None}
            links = await self.get_review_tag_link_list_by_tag_id(tag_ids, tenant_id)
            for link in links:
                user_id = int(link.user_id or 0)
                if user_id <= 0 or user_id in user_targets:
                    continue
                space_id, file_id, file_name, file_type = await self._resolve_file_target_from_link(link, tenant_id)
                if space_id is None:
                    parent_tag = tag_by_id.get(int(link.tag_id))
                    space_id = self._space_id_from_review_tag(parent_tag) if parent_tag else None
                    if space_id is None and parent_tag and parent_tag.id is not None:
                        space_id = await self._resolve_space_id_from_tag_links(int(parent_tag.id), tenant_id)
                user_targets[user_id] = ReviewTagSubmitterTarget(
                    user_id=user_id,
                    knowledge_space_id=space_id,
                    file_id=file_id,
                    file_name=file_name,
                    file_type=file_type,
                )

        if exclude_user_id is not None:
            user_targets.pop(int(exclude_user_id), None)
        return list(user_targets.values())

    async def list_all_tags_by_page(self, page: int, page_size: int, keyword: str, tenant_id: int):
        return await self.tags_repository.list_all_tags_by_page(page, page_size, keyword, tenant_id)

    async def query_all_tag_library_count_by_page(self, keyword: str, tenant_id: int):
        return await self.tags_repository.get_all_tag_library_count_by_page(keyword, tenant_id)

    async def delete_tag_library_by_manual_tag(self, tag_name: str, resource_type: TagResourceTypeEnum, tenant_id: int):
        tag_list = await self.tags_repository.get_tag_list_by_tag_name(tag_name, resource_type, tenant_id)
        if tag_list and len(tag_list) > 0:
            tag_ids = [tag.id for tag in tag_list]
            tag_link_count = await self.tags_repository.get_tag_link_count_by_tag_id(tag_ids, tenant_id)
            if tag_link_count > 0:
                raise TargetTagInUsedError.http_exception()
            else:
                await self.tags_repository.delete_tag_library_by_name(tag_name, resource_type, tenant_id)

    async def query_existed_tag_by_review_tag(self, review_tag: ReviewTag):
        return await self.tags_repository.query_existed_tag_by_review_tag(review_tag)

    async def get_not_exist_system_tag_by_name(self, keyword: str, tenant_id: int):
        tag_library = await self.tags_repository.get_tag_library(tenant_id)
        if tag_library:
            tags = tag_library.tags or []
            ai_tags = tag_library.ai_tags or []
            result = dict.fromkeys(tags, TagResourceTypeEnum.SYSTEM_TAG)

            all_tags_list = await self.tags_repository.get_all_library_list(tag_library)
            if keyword:
                tags_list = []
                for tag in all_tags_list:
                    if keyword in tag:
                        tags_list.append(tag)
                return tags_list, result
            else:
                return all_tags_list, result
        else:
            return [], {}
