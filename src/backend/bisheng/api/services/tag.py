import json
from typing import List

from fastapi import Request
from loguru import logger

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import UnAuthorizedError, NotFoundError
from bisheng.common.errcode.tag import TagExistError, TagNotExistError
from bisheng.common.models.config import ConfigDao, ConfigKeyEnum, Config
from bisheng.database.models.assistant import AssistantDao
from bisheng.database.models.flow import FlowDao
from bisheng.database.models.group_resource import ResourceTypeEnum, GroupResourceDao
from bisheng.database.models.role_access import AccessType
from bisheng.database.models.tag import TagDao, Tag, TagLink


class TagService:

    @classmethod
    def get_all_tag(cls,
                    request: Request,
                    login_user: UserPayload,
                    keyword: str = None, page: int = 0, limit: int = 10) -> (List[Tag], int):
        """ Get all tags """
        result = TagDao.search_tags(keyword, page, limit)
        return result, TagDao.count_tags(keyword)

    @classmethod
    def create_tag(cls,
                   request: Request,
                   login_user: UserPayload,
                   name: str) -> Tag:
        # Query if there is a renaming of the label name
        exist_tag = TagDao.get_tag_by_name(name)
        if exist_tag:
            raise TagExistError.http_exception()
        new_tag = Tag(name=name, user_id=login_user.user_id)
        new_tag = TagDao.insert_tag(new_tag)
        return new_tag

    @classmethod
    def update_tag(cls,
                   request: Request,
                   login_user: UserPayload,
                   tag_id: int,
                   name: str) -> Tag:
        tag_info = TagDao.get_tag_by_id(tag_id)
        if not tag_info:
            raise TagNotExistError.http_exception()
        # Query if there is a renaming of the label name
        exist_tag = TagDao.get_tag_by_name(name)
        if exist_tag and exist_tag.id != tag_id:
            raise TagExistError.http_exception()

        tag_info.name = name
        new_tag = TagDao.insert_tag(tag_info)
        return new_tag

    @classmethod
    def delete_tag(cls,
                   request: Request,
                   login_user: UserPayload,
                   tag_id: int) -> bool:
        """ NO NAME SPACE NO KEY VALUE!! """
        return TagDao.delete_tag(tag_id)

    @classmethod
    def check_tag_link_permission(cls,
                                  request: Request,
                                  login_user: UserPayload,
                                  resource_id: str,
                                  resource_type: ResourceTypeEnum) -> bool:
        """ Check if labeling of resources is allowed """
        if login_user.is_admin():
            return True
        resource_info = None
        access_type: AccessType
        if resource_type == ResourceTypeEnum.ASSISTANT:
            resource_info = AssistantDao.get_one_assistant(resource_id)
            access_type = AccessType.ASSISTANT_WRITE
        elif resource_type == ResourceTypeEnum.FLOW:
            resource_info = FlowDao.get_flow_by_id(resource_id)
            access_type = AccessType.FLOW_WRITE
        elif resource_type == ResourceTypeEnum.WORK_FLOW:
            resource_info = FlowDao.get_flow_by_id(resource_id)
            access_type = AccessType.WORKFLOW_WRITE
        else:
            raise NotFoundError()
        if not resource_info:
            raise NotFoundError()

        if login_user.access_check(resource_info.user_id, resource_id, access_type):
            return True

        # Get user groups to which the resource belongs
        resource_groups = GroupResourceDao.get_resource_group(resource_type, resource_id)
        resource_groups = [int(one.group_id) for one in resource_groups]
        # Determine if the operator under is an administrator of a user group
        if not login_user.check_groups_admin(resource_groups):
            raise UnAuthorizedError()

        return True

    @classmethod
    def create_tag_link(cls,
                        request: Request,
                        login_user: UserPayload,
                        tag_id: int,
                        resource_id: str,
                        resource_type: ResourceTypeEnum) -> TagLink:
        """ Associate resources with tags """
        cls.check_tag_link_permission(request, login_user, resource_id, resource_type)

        new_link = TagLink(tag_id=tag_id, resource_id=resource_id, resource_type=resource_type.value,
                           user_id=login_user.user_id)
        try:
            new_link = TagDao.insert_tag_link(new_link)
        except Exception as e:
            logger.error(f'tag_link_error: {e}')
            raise TagExistError.http_exception()
        return new_link

    @classmethod
    def delete_tag_link(cls,
                        request: Request,
                        login_user: UserPayload,
                        tag_id: int,
                        resource_id: str,
                        resource_type: ResourceTypeEnum) -> bool:
        """ Remove association of resources and tags """
        cls.check_tag_link_permission(request, login_user, resource_id, resource_type)

        return TagDao.delete_resource_tag(tag_id, resource_id, resource_type)

    @classmethod
    def get_home_tag(cls,
                     request: Request,
                     login_user: UserPayload) -> List[Tag]:
        """ Get a list of tags to show on the homepage """
        home_tags = ConfigDao.get_config(ConfigKeyEnum.HOME_TAGS)
        if not home_tags:
            return []
        home_tags = json.loads(home_tags.value)
        tags = TagDao.get_tags_by_ids(home_tags)

        tags = sorted(tags, key=lambda x: home_tags.index(x.id))
        return tags

    @classmethod
    def update_home_tag(cls,
                        request: Request,
                        login_user: UserPayload,
                        tag_ids: List[int]) -> bool:
        """ Update the list of tags displayed on the homepage """
        home_tags = ConfigDao.get_config(ConfigKeyEnum.HOME_TAGS)
        if not home_tags:
            home_tags = Config(key=ConfigKeyEnum.HOME_TAGS.value, value=json.dumps(tag_ids))
        else:
            home_tags.value = json.dumps(tag_ids)

        ConfigDao.insert_config(home_tags)
        return True
