from typing import Optional

from bisheng.common.services.base import BaseService
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.database.models.tag import TagBusinessTypeEnum, TagResourceTypeEnum
from bisheng.workstation.domain.repositories.review_tags_repository import ReviewTagsRepositoryImpl
from bisheng.workstation.domain.schemas.review_tags_schema import ApproveOrRejectRequest
from bisheng.database.models.review_tags import ApproveOrRejectEnum
from bisheng.common.errcode.tag import ReviewTagTypeMismatchError, ReviewTagNotFoundError, TagNameParamsIsEmptyError, TagPageParamsIsError, TagPageSizeParamsIsError


class WorkStationTagsService(BaseService):

    def __init__(self, request: Request, session: AsyncSession, login_user: UserPayload, review_tags_repository: ReviewTagsRepositoryImpl):
        super().__init__()
        self.request = request
        self.session = session
        self.review_tags_repository = review_tags_repository
        self.login_user = login_user

    async def delete_review_tag(self, tag_name: str, business_type: TagBusinessTypeEnum, tenant_id: int):
        review_tag_list = await self.review_tags_repository.get_review_tag_list_by_tag_name(tag_name, tenant_id)
        if review_tag_list:
            for review_tag in review_tag_list:
                await self.review_tags_repository.delete_tag_id(review_tag.id, business_type.value, tenant_id)
            await self.session.commit()

    async def approve_or_reject_review_tag(self, data: ApproveOrRejectRequest, tenant_id: int):
        if data and data.status == ApproveOrRejectEnum.APPROVE:
            await self.approve_tag_to_move_operation(data.tag_name, tenant_id)
            await self.review_tags_repository.approve_review_tag(data.tag_name, tenant_id)
            await self.session.commit()
        elif data and data.status == ApproveOrRejectEnum.REJECT:
            await self.review_tags_repository.reject_review_tag(data.tag_name, data.reject_reason, tenant_id)
            await self.session.commit()
        else:
            raise ReviewTagTypeMismatchError.http_exception()


    async def approve_tag_to_move_operation(self, tag_name: str, tenant_id: int):
        review_tag_list = await self.review_tags_repository.get_review_tag_list_by_tag_name(tag_name, tenant_id)
        if not review_tag_list:
            raise ReviewTagNotFoundError.http_exception()
        for review_tag in review_tag_list:
            review_tag_link = await self.review_tags_repository.query_review_tag_link_list_by_tag_id(review_tag.id, tenant_id)
            if not review_tag_link:
                review_tag_link = []
            await self.review_tags_repository.approve_tag_to_move(review_tag, review_tag_link)

    async def create_tag_library_by_name(self, tag_name: str, tenant_id: int):
        if not tag_name:
            raise TagNameParamsIsEmptyError.http_exception()
        await self.review_tags_repository.create_tag_library_by_tag(tag_name, tenant_id, TagResourceTypeEnum.SYSTEM_TAG)
        await self.session.commit()

    async def update_tag_library_by_name(self, original_tag_name: str, tag_name: str, resource_type: TagResourceTypeEnum, tenant_id: int):
        if not tag_name or not original_tag_name:
            raise TagNameParamsIsEmptyError.http_exception()
        await self.review_tags_repository.update_tag_library_by_tag(original_tag_name, tag_name, resource_type, tenant_id)
        await self.session.commit()

    async def delete_tag_library_by_name(self, tag_name: str, resource_type: TagResourceTypeEnum, tenant_id: int):
        if not tag_name:
            raise TagNameParamsIsEmptyError.http_exception()
        await self.review_tags_repository.delete_tag_library_by_tag(tag_name, resource_type, tenant_id)
        await self.session.commit()


    async def list_tag_library_by_name(self, tag_name: str, tenant_id: int):
        tags_list, result_dict = await self.review_tags_repository.get_list_tag_library_by_name(tag_name, tenant_id)
        result_list = []
        if tags_list and len(tags_list) > 0:
            for tag in tags_list:
                tag_obj = await self.review_tags_repository.get_tag_info_by_tag(tag, tenant_id)
                if tag_obj:
                    tag_obj["resource_type"] = result_dict.get(tag, TagResourceTypeEnum.AI_AUTO_TAG)
                    result_list.append(tag_obj)
        return result_list
            
            
    async def list_review_tag_by_page(self, page: int, page_size: int, tenant_id: int):
        if not page or page < 1:
            raise TagPageParamsIsError.http_exception()
        if not page_size or page_size < 1:
            raise TagPageSizeParamsIsError.http_exception()

        group_tag_list = await self.review_tags_repository.get_review_tag_group_list_by_page(page, page_size, tenant_id)
        result_list = []
        if group_tag_list and len(group_tag_list) > 0:
            for group_tag in group_tag_list:
                tag_obj = await self.review_tags_repository.get_review_tag_resource_info_by_tag(group_tag, tenant_id)
                if tag_obj:
                    result_list.append(tag_obj)
        total_count = await self.review_tags_repository.get_review_tag_group_count_by_page(tenant_id)
        return {"data": result_list or [], "total": total_count or 0}
