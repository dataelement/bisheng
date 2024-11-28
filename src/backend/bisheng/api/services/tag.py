import json
from typing import List
from uuid import UUID

from fastapi import Request, HTTPException

from bisheng.api.errcode.base import UnAuthorizedError
from bisheng.api.errcode.tag import TagExistError, TagNotExistError
from bisheng.api.services.user_service import UserPayload
from bisheng.database.models.assistant import AssistantDao
from bisheng.database.models.config import ConfigDao, ConfigKeyEnum, Config
from bisheng.database.models.flow import FlowDao
from bisheng.database.models.group_resource import ResourceTypeEnum, GroupResourceDao
from bisheng.database.models.tag import TagDao, Tag, TagLink


class TagService:

    @classmethod
    def get_all_tag(cls,
                    request: Request,
                    login_user: UserPayload,
                    keyword: str = None, page: int = 0, limit: int = 10) -> (List[Tag], int):
        """ 获取所有的标签 """
        result = TagDao.search_tags(keyword, page, limit)
        return result, TagDao.count_tags(keyword)

    @classmethod
    def create_tag(cls,
                   request: Request,
                   login_user: UserPayload,
                   name: str) -> Tag:
        # 查询是否有重名的标签名称
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
        # 查询是否有重名的标签名称
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
        """ 删除标签 """
        return TagDao.delete_tag(tag_id)

    @classmethod
    def check_tag_link_permission(cls,
                                  request: Request,
                                  login_user: UserPayload,
                                  resource_id: str,
                                  resource_type: ResourceTypeEnum) -> bool:
        """ 检查是否允许给资源打标签 """
        if login_user.is_admin():
            return True
        resource_info = None
        if resource_type == ResourceTypeEnum.ASSISTANT:
            resource_info = AssistantDao.get_one_assistant(UUID(resource_id))
        elif resource_type == ResourceTypeEnum.FLOW:
            resource_info = FlowDao.get_flow_by_id(UUID(resource_id).hex)
        elif resource_type == ResourceTypeEnum.WORK_FLOW:
            resource_info = FlowDao.get_flow_by_id(UUID(resource_id).hex)
        else:
            raise HTTPException(status_code=404, detail="资源类型不支持")
        if not resource_info:
            raise HTTPException(status_code=404, detail="资源不存在")
        # 是资源的创建人
        if resource_info.user_id == login_user.user_id:
            return True

        # 获取资源所属的用户组
        resource_groups = GroupResourceDao.get_resource_group(resource_type, resource_id)
        resource_groups = [int(one.group_id) for one in resource_groups]
        # 判断下操作人是否是用户组的管理员
        if not login_user.check_groups_admin(resource_groups):
            raise UnAuthorizedError.http_exception()

        return True

    @classmethod
    def create_tag_link(cls,
                        request: Request,
                        login_user: UserPayload,
                        tag_id: int,
                        resource_id: str,
                        resource_type: ResourceTypeEnum) -> TagLink:
        """ 建立资源和标签的关联 """
        cls.check_tag_link_permission(request, login_user, resource_id, resource_type)

        new_link = TagLink(tag_id=tag_id, resource_id=UUID(resource_id).hex, resource_type=resource_type.value,
                           user_id=login_user.user_id)
        new_link = TagDao.insert_tag_link(new_link)
        return new_link

    @classmethod
    def delete_tag_link(cls,
                        request: Request,
                        login_user: UserPayload,
                        tag_id: int,
                        resource_id: str,
                        resource_type: ResourceTypeEnum) -> bool:
        """ 删除资源和标签的关联 """
        cls.check_tag_link_permission(request, login_user, resource_id, resource_type)

        return TagDao.delete_resource_tag(tag_id, UUID(resource_id).hex, resource_type)

    @classmethod
    def get_home_tag(cls,
                     request: Request,
                     login_user: UserPayload) -> List[Tag]:
        """ 获取首页展示的标签列表 """
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
        """ 更新首页展示的标签列表 """
        home_tags = ConfigDao.get_config(ConfigKeyEnum.HOME_TAGS)
        if not home_tags:
            home_tags = Config(key=ConfigKeyEnum.HOME_TAGS.value, value=json.dumps(tag_ids))
        else:
            home_tags.value = json.dumps(tag_ids)

        ConfigDao.insert_config(home_tags)
        return True
