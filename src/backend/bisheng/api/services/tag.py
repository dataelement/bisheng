import json

from fastapi import Request
from loguru import logger

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import NotFoundError
from bisheng.common.errcode.tag import TagExistError, TagNotExistError
from bisheng.common.models.config import ConfigDao, ConfigKeyEnum
from bisheng.core.context.tenant import strict_tenant_filter
from bisheng.core.database.tenant_filter import _resolve_tenant_id
from bisheng.database.models.assistant import AssistantDao
from bisheng.database.models.flow import FlowDao
from bisheng.database.models.group_resource import ResourceTypeEnum
from bisheng.database.models.tag import Tag, TagBusinessTypeEnum, TagDao, TagLink
from bisheng.permission.application.business_authorization import (
    require_business_action,
)
from bisheng.utils.async_utils import run_async_safe
from bisheng.workstation.domain.models.tenant_workstation_config import TenantWorkstationConfigDao


async def _aget_hosted_app(resource_id: str):
    """One hosted application row, or ``None`` once it is deleted.

    Deliberately not routed through ``AppQueryService``: that service answers
    the detail page's question (owner or tenant administrator), while tagging
    asks the generic F048 ``edit`` question a few lines below. Reusing it would
    quietly apply two different rules to the same request. A ``deleted`` app is
    reported as absent — the row survives for audit, but it is not a resource
    anyone should be attaching tags to.
    """
    from bisheng.core.database import get_async_db_session
    from bisheng.database.models.app import APP_STATE_DELETED, AppDao

    async with get_async_db_session() as session:
        row = await AppDao.aget(session, resource_id)
    if row is None or row.state == APP_STATE_DELETED:
        return None
    return row


class TagService:
    @classmethod
    def get_all_tag(
        cls, request: Request, login_user: UserPayload, keyword: str | None = None, page: int = 0, limit: int = 10
    ) -> tuple[list[Tag], int]:
        """Get all tags"""
        with strict_tenant_filter():
            result = TagDao.search_tags(
                keyword,
                page,
                limit,
                business_type=TagBusinessTypeEnum.APPLICATION,
                business_id=TagBusinessTypeEnum.APPLICATION.value,
            )
            return result, TagDao.count_tags(
                keyword,
                business_type=TagBusinessTypeEnum.APPLICATION,
                business_id=TagBusinessTypeEnum.APPLICATION.value,
            )

    @classmethod
    def create_tag(cls, request: Request, login_user: UserPayload, name: str) -> Tag:
        # Query if there is a renaming of the label name
        exist_tag = TagDao.get_tag_by_name(name)
        if exist_tag:
            raise TagExistError.http_exception()
        new_tag = Tag(
            name=name,
            user_id=login_user.user_id,
            business_type=TagBusinessTypeEnum.APPLICATION,
            business_id=TagBusinessTypeEnum.APPLICATION.value,
        )
        new_tag = TagDao.insert_tag(new_tag)
        return new_tag

    @classmethod
    def update_tag(cls, request: Request, login_user: UserPayload, tag_id: int, name: str) -> Tag:
        tag_info = TagDao.get_tag_by_id(tag_id)
        if not tag_info:
            raise TagNotExistError.http_exception()
        # Query if there is a renaming of the label name
        exist_tag = TagDao.get_tag_by_name(name)
        if exist_tag and exist_tag.id != tag_id:
            raise TagExistError.http_exception()

        tag_info.name = name
        new_tag = TagDao.update_tag(tag_info)
        return new_tag

    @classmethod
    def delete_tag(cls, request: Request, login_user: UserPayload, tag_id: int) -> bool:
        if TagDao.get_tag_by_id(tag_id) is None:
            raise TagNotExistError()
        return TagDao.delete_tag(tag_id)

    @classmethod
    def check_tag_link_permission(
        cls, request: Request, login_user: UserPayload, resource_id: str, resource_type: ResourceTypeEnum
    ) -> bool:
        """Check if labeling of resources is allowed"""
        resource_info = None
        f048_resource_type: str
        if resource_type == ResourceTypeEnum.ASSISTANT:
            resource_info = AssistantDao.get_one_assistant(resource_id)
            f048_resource_type = "assistant"
        elif resource_type == ResourceTypeEnum.WORK_FLOW:
            resource_info = FlowDao.get_flow_by_id(resource_id)
            f048_resource_type = "workflow"
        elif resource_type == ResourceTypeEnum.HOSTED_APP:
            # F054: without this branch the fall-through raises NotFoundError,
            # so tagging a hosted application answers 404 while the tag filter
            # on the list page looks like it works — the failure lands nowhere
            # near its cause (design D8, gate 5).
            resource_info = run_async_safe(_aget_hosted_app(resource_id))
            f048_resource_type = "app"
        else:
            raise NotFoundError()
        if not resource_info:
            raise NotFoundError()

        run_async_safe(
            require_business_action(
                login_user,
                resource_type=f048_resource_type,
                resource_id=resource_id,
                action="edit",
            )
        )

        return True

    @classmethod
    def create_tag_link(
        cls, request: Request, login_user: UserPayload, tag_id: int, resource_id: str, resource_type: ResourceTypeEnum
    ) -> TagLink:
        """Associate resources with tags"""
        if TagDao.get_tag_by_id(tag_id) is None:
            raise TagNotExistError()
        cls.check_tag_link_permission(request, login_user, resource_id, resource_type)

        new_link = TagLink(
            tag_id=tag_id, resource_id=resource_id, resource_type=resource_type.value, user_id=login_user.user_id
        )
        try:
            new_link = TagDao.insert_tag_link(new_link)
        except Exception as e:
            logger.error(f"tag_link_error: {e}")
            raise TagExistError.http_exception()
        return new_link

    @classmethod
    def delete_tag_link(
        cls, request: Request, login_user: UserPayload, tag_id: int, resource_id: str, resource_type: ResourceTypeEnum
    ) -> bool:
        """Remove association of resources and tags"""
        cls.check_tag_link_permission(request, login_user, resource_id, resource_type)

        return TagDao.delete_resource_tag(tag_id, resource_id, resource_type)

    @classmethod
    async def get_home_tag(cls, request: Request, login_user: UserPayload) -> list[Tag]:
        """Get a list of tags to show on the homepage"""
        home_tags = await TenantWorkstationConfigDao.aget(_resolve_tenant_id(), ConfigKeyEnum.HOME_TAGS.value)
        if home_tags is None:
            # Keep legacy ordering until this tenant saves its own selection.
            # Tag reads below still exclude every foreign tenant's IDs.
            home_tags = await ConfigDao.aget_config(ConfigKeyEnum.HOME_TAGS)
        if not home_tags:
            return []
        home_tags = json.loads(home_tags.value)
        with strict_tenant_filter():
            tags = await TagDao.aget_tags_by_ids(home_tags)

        tags = sorted(tags, key=lambda x: home_tags.index(x.id))
        return tags

    @classmethod
    async def update_home_tag(cls, request: Request, login_user: UserPayload, tag_ids: list[int]) -> bool:
        """Update the list of tags displayed on the homepage"""
        tag_ids = list(dict.fromkeys(tag_ids))
        tags = await TagDao.aget_tags_by_ids(tag_ids)
        if {tag.id for tag in tags} != set(tag_ids):
            raise TagNotExistError()
        await TenantWorkstationConfigDao.aupsert(
            _resolve_tenant_id(), ConfigKeyEnum.HOME_TAGS.value, json.dumps(tag_ids)
        )
        return True
