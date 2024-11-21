from typing import Dict, List
from uuid import UUID
from bisheng.api.services.base import BaseService
from bisheng.api.services.user_service import UserPayload
from bisheng.api.v1.schemas import UnifiedResponseModel, resp_200
from bisheng.database.models.assistant import AssistantDao
from bisheng.database.models.flow import FlowDao, FlowType
from bisheng.database.models.flow_version import FlowVersionDao
from bisheng.database.models.group_resource import GroupResourceDao, ResourceTypeEnum
from bisheng.database.models.role_access import AccessType, RoleAccessDao
from bisheng.database.models.tag import TagDao
from bisheng.database.models.user import UserDao
from bisheng.database.models.user_role import UserRoleDao

from fastapi.encoders import jsonable_encoder

class WorkFlowService(BaseService):

    def get_all_flows(cls, user: UserPayload, name: str, status: int, tag_id: int = 0, page: int = 1,
                      page_size: int = 10, flow_type :int = FlowType.FLOW.value) -> UnifiedResponseModel[List[Dict]]:
        """
        获取所有技能
        """
        flow_ids = []
        if tag_id:
            ret = TagDao.get_resources_by_tags([tag_id], ResourceTypeEnum.FLOW)
            assistant = TagDao.get_resources_by_tags([tag_id], ResourceTypeEnum.ASSISTANT)
            ret = ret + assistant
            flow_ids = [UUID(one.resource_id) for one in ret]
            assistant_ids = [UUID(one.resource_id) for one in assistant]
            if not assistant_ids:
                return resp_200(data={
                    'data': [],
                    'total': 0
                })

        half_page = page_size/2
        # 获取用户可见的技能列表
        if user.is_admin():
            fdata = FlowDao.get_flows(user.user_id, "admin", name, status, flow_ids, page, page_size=half_page)
            ares, atotal = AssistantDao.get_all_assistants(name, page, limit=half_page, assistant_ids, status)
            ftotal = FlowDao.count_flows(user.user_id, "admin", name, status, flow_ids)
            data = fdata + ares 
            total = ftotal + atotal
        else:
            user_role = UserRoleDao.get_user_roles(user.user_id)
            role_ids = [role.role_id for role in user_role]
            role_access = RoleAccessDao.get_role_access(role_ids, AccessType.FLOW)
            a_role_access = RoleAccessDao.get_role_access(role_ids, AccessType.ASSISTANT_READ)
            flow_id_extra = []
            assistant_ids_extra = []
            if role_access:
                flow_id_extra = [access.third_id for access in role_access]
            data = FlowDao.get_flows(user.user_id, flow_id_extra, name, status, flow_ids, page, page_size=half_page)
            total = FlowDao.count_flows(user.user_id, flow_id_extra, name, status, flow_ids)
            if a_role_access:
                assistant_ids_extra = [UUID(access.third_id).hex for access in a_role_access]
            a_res, a_total = AssistantDao.get_assistants(user.user_id, name, assistant_ids_extra, status, page, limit=half_page,assistant_ids)
            data = data + a_res
            total = total + a_total


        # 获取技能列表对应的用户信息和版本信息
        # 技能ID列表
        flow_ids = []
        # 技能创建用户的ID列表
        user_ids = []
        for one in data:
            flow_ids.append(one.id.hex)
            user_ids.append(one.user_id)
        # 获取列表内的用户信息
        user_infos = UserDao.get_user_by_ids(user_ids)
        user_dict = {one.user_id: one.user_name for one in user_infos}

        # 获取列表内的版本信息
        version_infos = FlowVersionDao.get_list_by_flow_ids(flow_ids)
        flow_versions = {}
        for one in version_infos:
            if one.flow_id not in flow_versions:
                flow_versions[one.flow_id] = []
            flow_versions[one.flow_id].append(jsonable_encoder(one))

        # 获取技能所属的分组
        flow_groups = GroupResourceDao.get_resources_group(ResourceTypeEnum.FLOW, flow_ids)
        flow_group_dict = {}
        for one in flow_groups:
            if one.third_id not in flow_group_dict:
                flow_group_dict[one.third_id] = []
            flow_group_dict[one.third_id].append(one.group_id)

        # 获取技能关联的tag
        flow_tags = TagDao.get_tags_by_resource(ResourceTypeEnum.FLOW, flow_ids)

        # 重新拼接技能列表list信息
        res = []
        for one in data:
            one.logo = cls.get_logo_share_link(one.logo)
            flow_info = jsonable_encoder(one)
            flow_info['user_name'] = user_dict.get(one.user_id, one.user_id)
            flow_info['write'] = True if user.is_admin() or user.user_id == one.user_id else False
            flow_info['version_list'] = flow_versions.get(one.id.hex, [])
            flow_info['group_ids'] = flow_group_dict.get(one.id.hex, [])
            flow_info['tags'] = flow_tags.get(one.id.hex, [])

            res.append(flow_info)

        return resp_200(data={
            "data": res,
            "total": total
        })
