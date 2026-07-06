from fastapi import Request
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import KnowledgeSpaceTagLibraryInvalidError
from bisheng.common.errcode.tag import (
    ReviewTagNotFoundError,
    ReviewTagTypeMismatchError,
    TagNameParamsIsEmptyError,
    TagPageParamsIsError,
    TagPageSizeParamsIsError,
)
from bisheng.common.services.base import BaseService
from bisheng.database.models.review_tags import ApproveOrRejectEnum
from bisheng.database.models.tag import TagBusinessTypeEnum, TagResourceTypeEnum
from bisheng.workstation.domain.repositories.review_tags_repository import ReviewTagsRepositoryImpl
from bisheng.workstation.domain.schemas.review_tags_schema import ApproveOrRejectRequest
from bisheng.workstation.domain.services.review_tag_notification_service import (
    ReviewTagNotificationService,
    ReviewTagSubmitterTarget,
)


class WorkStationTagsService(BaseService):
    def __init__(
        self,
        request: Request,
        session: AsyncSession,
        login_user: UserPayload,
        review_tags_repository: ReviewTagsRepositoryImpl,
    ):
        super().__init__()
        self.request = request
        self.session = session
        self.review_tags_repository = review_tags_repository
        self.login_user = login_user

    async def delete_review_tag(
        self, tag_name: str, business_type: TagBusinessTypeEnum, resource_type: TagResourceTypeEnum, tenant_id: int
    ):
        review_tag_list = await self.review_tags_repository.get_review_tag_list_by_tag_name(
            tag_name, resource_type, tenant_id
        )
        if review_tag_list:
            for review_tag in review_tag_list:
                await self.review_tags_repository.delete_review_tag_id(
                    review_tag.id, business_type.value, resource_type, tenant_id
                )
            await self.session.commit()

    async def approve_or_reject_review_tag(self, data: ApproveOrRejectRequest, tenant_id: int):
        existed_tag_list = []
        submitter_targets = [
            ReviewTagSubmitterTarget(user_id=user_id, knowledge_space_id=space_id)
            for user_id, space_id in await self.review_tags_repository.list_submitter_notification_targets(
                data.tag_name,
                data.resource_type,
                tenant_id,
                exclude_user_id=self.login_user.user_id,
            )
        ]
        if data and data.status == ApproveOrRejectEnum.APPROVE:
            if not data.tag_library_id or not data.knowledge_id:
                raise KnowledgeSpaceTagLibraryInvalidError(msg="请选择导入的标签库")
            from bisheng.knowledge.domain.services.knowledge_space_tag_library_service import (
                KnowledgeSpaceTagLibraryService,
            )

            tag_library_service = KnowledgeSpaceTagLibraryService(self.login_user)
            await tag_library_service.append_review_tag(
                library_id=int(data.tag_library_id),
                knowledge_id=int(data.knowledge_id),
                tag_name=data.tag_name,
                review_resource_type=data.resource_type.value,
            )
            existed_tag_list = await self.approve_tag_to_move_operation(
                data.tag_name,
                data.resource_type,
                tenant_id,
                skip_library_add=True,
            )
            await self.review_tags_repository.approve_review_tag(data.tag_name, data.resource_type, tenant_id)
            await self.session.commit()
        elif data and data.status == ApproveOrRejectEnum.REJECT:
            await self.review_tags_repository.reject_review_tag(
                data.tag_name, data.reject_reason, data.resource_type, tenant_id
            )
            await self.session.commit()
        else:
            raise ReviewTagTypeMismatchError.http_exception()

        await ReviewTagNotificationService.notify_after_decision(
            sender=self.login_user.user_id,
            sender_user_name=getattr(self.login_user, "user_name", None),
            tag_name=data.tag_name,
            status=data.status,
            submitter_targets=submitter_targets,
            reject_reason=data.reject_reason,
            fallback_knowledge_id=data.knowledge_id,
        )
        return existed_tag_list

    async def approve_tag_to_move_operation(
        self,
        tag_name: str,
        resource_type: TagResourceTypeEnum,
        tenant_id: int,
        *,
        skip_library_add: bool = False,
    ):
        review_tag_list = await self.review_tags_repository.get_review_tag_list_by_tag_name(
            tag_name, resource_type, tenant_id
        )
        existed_tag_list = []
        if not review_tag_list:
            raise ReviewTagNotFoundError.http_exception()
        for review_tag in review_tag_list:
            existed_tag = await self.review_tags_repository.query_existed_tag_by_review_tag(review_tag)
            if existed_tag:
                logger.error(f"tag {review_tag.name} already existed")
                existed_tag_list.append(review_tag)
                continue
            review_tag_link = await self.review_tags_repository.query_review_tag_link_list_by_tag_id(
                review_tag.id, tenant_id
            )
            if not review_tag_link:
                review_tag_link = []
            await self.review_tags_repository.approve_tag_to_move(
                review_tag,
                review_tag_link,
                skip_library_add=skip_library_add,
            )
        return existed_tag_list

    async def create_tag_library_by_name(self, tag_name: str, tenant_id: int):
        if not tag_name:
            raise TagNameParamsIsEmptyError.http_exception()
        await self.review_tags_repository.create_tag_library_by_tag(tag_name, tenant_id, TagResourceTypeEnum.SYSTEM_TAG)
        await self.session.commit()

    async def update_tag_library_by_name(
        self, original_tag_name: str, tag_name: str, resource_type: TagResourceTypeEnum, tenant_id: int
    ):
        if not tag_name or not original_tag_name:
            raise TagNameParamsIsEmptyError.http_exception()
        if resource_type == TagResourceTypeEnum.SYSTEM_TAG or resource_type == TagResourceTypeEnum.AI_AUTO_TAG:
            await self.review_tags_repository.update_tag_library_by_tag(
                original_tag_name, tag_name, resource_type, tenant_id
            )
        elif resource_type == TagResourceTypeEnum.MANUAL_TAG:
            await self.review_tags_repository.update_tag_library_by_manual_tag(
                original_tag_name, tag_name, resource_type, tenant_id
            )
        await self.session.commit()

    async def delete_tag_library_by_name(self, tag_name: str, resource_type: TagResourceTypeEnum, tenant_id: int):
        if not tag_name or not resource_type:
            raise TagNameParamsIsEmptyError.http_exception()
        if resource_type == TagResourceTypeEnum.SYSTEM_TAG or resource_type == TagResourceTypeEnum.AI_AUTO_TAG:
            await self.review_tags_repository.delete_tag_library_by_tag(tag_name, resource_type, tenant_id)
        elif resource_type == TagResourceTypeEnum.MANUAL_TAG:
            await self.review_tags_repository.delete_tag_library_by_manual_tag(tag_name, resource_type, tenant_id)
        await self.session.commit()

    async def list_tag_library_by_name(self, keyword: str, tenant_id: int):
        tags_list, result_dict = await self.review_tags_repository.get_list_tag_library_by_name(keyword, tenant_id)
        result_list = []
        if tags_list and len(tags_list) > 0:
            for tag in tags_list:
                tag_obj = await self.review_tags_repository.get_tag_info_by_tag(
                    tag, result_dict.get(tag, TagResourceTypeEnum.AI_AUTO_TAG), tenant_id
                )
                if tag_obj:
                    result_list.append(tag_obj)
        return result_list

    async def list_review_tag_by_page(self, page: int, page_size: int, tenant_id: int, keyword: str = ""):
        if not page or page < 1:
            raise TagPageParamsIsError.http_exception()
        if not page_size or page_size < 1:
            raise TagPageSizeParamsIsError.http_exception()

        normalized_keyword = (keyword or "").strip()
        group_tag_list = await self.review_tags_repository.get_review_tag_group_list_by_page(
            page, page_size, tenant_id, normalized_keyword
        )
        result_list = []
        if group_tag_list and len(group_tag_list) > 0:
            for group_tag in group_tag_list:
                tag_obj = await self.review_tags_repository.get_review_tag_resource_info_by_tag(
                    group_tag["name"], group_tag["resource_type"], tenant_id
                )
                if tag_obj:
                    result_list.append(tag_obj)
        total_count = await self.review_tags_repository.get_review_tag_group_count_by_page(
            tenant_id, normalized_keyword
        )
        return {"data": result_list or [], "total": total_count or 0}

    async def list_all_tags_library_by_page(self, keyword: str, page: int, page_size: int, tenant_id: int):
        if not page or page < 1:
            raise TagPageParamsIsError.http_exception()
        if not page_size or page_size < 1:
            raise TagPageSizeParamsIsError.http_exception()
        tag_list = await self.review_tags_repository.list_all_tags_by_page(page, page_size, keyword, tenant_id)
        result_list = []
        result_list.clear()
        if tag_list and len(tag_list) > 0:
            for tag in tag_list:
                tag_obj = await self.review_tags_repository.get_tag_info_by_tag(
                    tag["name"], tag["resource_type"], tenant_id
                )
                if tag_obj:
                    result_list.append(tag_obj)
        # 查找没有的数据
        data_list = await self.list_tag_library_by_keyword(keyword, tenant_id)
        if len(result_list) < page_size and data_list and len(data_list) > 0:
            count = min(page_size - len(result_list), len(data_list))
            result_list.extend(data_list[:count])

        total_count = await self.review_tags_repository.query_all_tag_library_count_by_page(keyword, tenant_id)
        total = int(total_count or 0) + len(data_list or [])
        return {"data": result_list or [], "total": total}

    async def list_tag_library_by_keyword(self, keyword: str, tenant_id: int):
        tags_list, result_dict = await self.review_tags_repository.get_not_exist_system_tag_by_name(keyword, tenant_id)
        result_list = []
        if tags_list and len(tags_list) > 0:
            for tag in tags_list:
                tag_obj = await self.review_tags_repository.get_not_exist_tag_info_by_tag(
                    tag, result_dict.get(tag, TagResourceTypeEnum.AI_AUTO_TAG), tenant_id
                )
                if tag_obj:
                    result_list.append(tag_obj)
        return result_list
