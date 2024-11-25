import json
from datetime import datetime
from typing import List, Any, Dict, Optional
from uuid import UUID

from fastapi.encoders import jsonable_encoder
from fastapi import Request, HTTPException

from bisheng.cache.redis import redis_client
from bisheng.api.services.assistant import AssistantService
from bisheng.api.services.audit_log import AuditLogService
from bisheng.api.services.user_service import UserPayload
from bisheng.api.errcode.user import UserGroupNotDeleteError
from bisheng.api.utils import get_request_ip
from bisheng.api.v1.schemas import resp_200
from bisheng.database.models.assistant import AssistantDao
from bisheng.database.models.flow import FlowDao, FlowType
from bisheng.database.models.gpts_tools import GptsToolsDao
from bisheng.database.models.group import Group, GroupCreate, GroupDao, GroupRead, DefaultGroup
from bisheng.database.models.group_resource import GroupResourceDao, ResourceTypeEnum
from bisheng.database.models.knowledge import KnowledgeDao
from bisheng.database.models.role import AdminRole, RoleDao
from bisheng.database.models.user import User, UserDao
from bisheng.database.models.user_role import UserRoleDao
from bisheng.database.models.user_group import UserGroupCreate, UserGroupDao, UserGroupRead
from loguru import logger


class RoleGroupService():

    def get_group_list(self, group_ids: List[int]) -> List[GroupRead]:
        """获取全量的group列表"""

        # 查询group
        if group_ids:
            groups = GroupDao.get_group_by_ids(group_ids)
        else:
            groups = GroupDao.get_all_group()
        # 查询user
        user_admin = UserGroupDao.get_groups_admins([group.id for group in groups])
        users_dict = {}
        if user_admin:
            user_ids = [user.user_id for user in user_admin]
            users = UserDao.get_user_by_ids(user_ids)
            users_dict = {user.user_id: user for user in users}

        groupReads = [GroupRead.validate(group) for group in groups]
        for group in groupReads:
            group.group_admins = [
                users_dict.get(user.user_id).model_dump() for user in user_admin
                if user.group_id == group.id
            ]
        return groupReads

    def create_group(self, request: Request, login_user: UserPayload, group: GroupCreate) -> Group:
        """新建用户组"""
        group_admin = group.group_admins
        group.create_user = login_user.user_id
        group.update_user = login_user.user_id
        group = GroupDao.insert_group(group)
        if group_admin:
            logger.info('set_admin group_admins={} group_id={}', group_admin, group.id)
            self.set_group_admin(request, login_user, group_admin, group.id)
        self.create_group_hook(request, login_user, group)
        return group

    def create_group_hook(self, request: Request, login_user: UserPayload, group: Group) -> bool:
        """ 新建用户组后置操作 """
        logger.info(f'act=create_group_hook user={login_user.user_name} group_id={group.id}')
        # 记录审计日志
        AuditLogService.create_user_group(login_user, get_request_ip(request), group)
        return True

    def update_group(self, request: Request, login_user: UserPayload, group: Group) -> Group:
        """更新用户组"""
        exist_group = GroupDao.get_user_group(group.id)
        if not exist_group:
            raise ValueError('用户组不存在')
        exist_group.group_name = group.group_name
        exist_group.remark = group.group_name
        exist_group.update_user = login_user.user_id
        exist_group.update_time = datetime.now()

        group = GroupDao.update_group(exist_group)
        self.update_group_hook(request, login_user, group)
        return group

    def update_group_hook(self, request: Request, login_user: UserPayload, group: Group):
        logger.info(f'act=update_group_hook user={login_user.user_name} group_id={group.id}')
        # 记录审计日志
        AuditLogService.update_user_group(login_user, get_request_ip(request), group)

    def delete_group(self, request: Request, login_user: UserPayload, group_id: int):
        """删除用户组"""
        if group_id == DefaultGroup:
            raise HTTPException(status_code=500, detail='默认组不能删除')
        group_info = GroupDao.get_user_group(group_id)
        if not group_info:
            return resp_200()

        # 判断组下是否还有用户
        user_group_list = UserGroupDao.get_group_user(group_id)
        if user_group_list:
            return UserGroupNotDeleteError.return_resp()
        GroupDao.delete_group(group_id)
        self.delete_group_hook(request, login_user, group_info)
        return resp_200()

    def delete_group_hook(self, request: Request, login_user: UserPayload, group_info: Group):
        logger.info(f'act=delete_group_hook user={login_user.user_name} group_id={group_info.id}')
        # 记录审计日志
        AuditLogService.delete_user_group(login_user, get_request_ip(request), group_info)
        # 将组下资源移到默认用户组
        # 获取组下所有的资源
        all_resource = GroupResourceDao.get_group_all_resource(group_info.id)
        need_move_resource = []
        for one in all_resource:
            # 获取资源属于几个组,属于多个组则不用处理, 否则将资源转移到默认用户组
            resource_groups = GroupResourceDao.get_resource_group(ResourceTypeEnum(one.type), one.third_id)
            if len(resource_groups) > 1:
                continue
            else:
                one.group_id = DefaultGroup
                need_move_resource.append(one)
        if need_move_resource:
            GroupResourceDao.update_group_resource(need_move_resource)
        GroupResourceDao.delete_group_resource_by_group_id(group_info.id)
        # 删除用户组下的角色列表
        RoleDao.delete_role_by_group_id(group_info.id)
        # 删除用户组的管理员
        UserGroupDao.delete_group_all_admin(group_info.id)
        # 将删除事件发到redis队列中
        delete_message = json.dumps({"id": group_info.id})
        redis_client.rpush('delete_group', delete_message)
        redis_client.expire_key('delete_group', 86400)
        redis_client.publish('delete_group', delete_message)

    def get_group_user_list(self, group_id: int, page_size: int, page_num: int) -> List[User]:
        """获取全量的group列表"""

        # 查询user
        user_group_list = UserGroupDao.get_group_user(group_id, page_size, page_num)
        if user_group_list:
            user_ids = [user.user_id for user in user_group_list]
            return UserDao.get_user_by_ids(user_ids)

        return None

    def insert_user_group(self, user_group: UserGroupCreate) -> UserGroupRead:
        """插入用户组"""

        user_groups = UserGroupDao.get_user_group(user_group.user_id)
        if user_groups and user_group.group_id in [ug.group_id for ug in user_groups]:
            raise ValueError('重复设置用户组')

        return UserGroupDao.insert_user_group(user_group)

    def replace_user_groups(self, request: Request, login_user: UserPayload, user_id: int, group_ids: List[int]):
        """ 覆盖用户的所在的用户组 """
        # 判断下被操作用户是否是超级管理员
        user_role_list = UserRoleDao.get_user_roles(user_id)
        if any(one.role_id == AdminRole for one in user_role_list):
            raise HTTPException(status_code=500, detail='系统管理员不允许编辑')

        # 获取用户之前的所有分组
        old_group = UserGroupDao.get_user_group(user_id)
        old_group = [one.group_id for one in old_group]
        if not login_user.is_admin():
            # 获取操作人所管理的组
            admin_group = UserGroupDao.get_user_admin_group(login_user.user_id)
            admin_group = [one.group_id for one in admin_group]
            # 过滤被操作人所在的组，只处理有权限管理的组
            old_group = [one for one in old_group if one in admin_group]
            # 说明此用户 不在此用户组管理员所管辖的用户组内
            if not old_group:
                raise ValueError('没有权限设置用户组')
        need_delete_group = old_group.copy()
        need_add_group = []
        for one in group_ids:
            if one not in old_group:
                # 需要加入的用户组
                need_add_group.append(one)
            else:
                # 旧的用户组里剩余的就是要移出的用户组
                need_delete_group.remove(one)
        if need_delete_group:
            UserGroupDao.delete_user_groups(user_id, need_delete_group)
        if need_add_group:
            UserGroupDao.add_user_groups(user_id, need_add_group)

        # 记录审计日志
        group_infos = GroupDao.get_group_by_ids(old_group + group_ids)
        group_dict: Dict[int, str] = {}
        for one in group_infos:
            group_dict[one.id] = one.group_name
        note = "编辑前用户组："
        for one in old_group:
            note += f'{group_dict.get(one, one)}、'
        note = note.rstrip('、')
        note += "编辑后用户组："
        for one in group_ids:
            note += f'{group_dict.get(one, one)}、'
        note = note.rstrip('、')
        AuditLogService.update_user(login_user, get_request_ip(request), user_id, group_dict.keys(), note)
        return None

    def get_user_groups_list(self, user_id: int) -> List[GroupRead]:
        """获取用户组列表"""
        user_groups = UserGroupDao.get_user_group(user_id)
        if not user_groups:
            return []
        group_ids = [ug.group_id for ug in user_groups]
        return GroupDao.get_group_by_ids(group_ids)

    def set_group_admin(self, request: Request, login_user: UserPayload, user_ids: List[int], group_id: int):
        """设置用户组管理员"""
        # 获取目前用户组的管理员列表
        user_group_admins = UserGroupDao.get_groups_admins([group_id])
        res = []
        need_delete_admin = []
        need_add_admin = user_ids
        if user_group_admins:
            for user in user_group_admins:
                if user.user_id in need_add_admin:
                    res.append(user)
                    need_add_admin.remove(user.user_id)
                else:
                    need_delete_admin.append(user.user_id)
        if need_add_admin:
            # 可以分配非组内用户为管理员。进行用户创建
            for user_id in need_add_admin:
                res.append(UserGroupDao.insert_user_group_admin(user_id, group_id))
        if need_delete_admin:
            UserGroupDao.delete_group_admins(group_id, need_delete_admin)
        # 修改用户组的最近修改人
        GroupDao.update_group_update_user(group_id, login_user.user_id)

        group_info = GroupDao.get_user_group(group_id)
        self.update_group_hook(request, login_user, group_info)
        return res

    def set_group_update_user(self, login_user: UserPayload, group_id: int):
        """设置用户组管理员"""
        GroupDao.update_group_update_user(group_id, login_user.user_id)

    def get_group_resources(self, group_id: int, resource_type: ResourceTypeEnum, name: str,
                            page_size: int, page_num: int) -> (List[Any], int):
        """ 获取用户下的资源 """
        if resource_type.value == ResourceTypeEnum.FLOW.value:
            return self.get_group_flow(group_id, name, page_size, page_num)
        elif resource_type.value == ResourceTypeEnum.KNOWLEDGE.value:
            return self.get_group_knowledge(group_id, name, page_size, page_num)
        elif resource_type.value == ResourceTypeEnum.WORK_FLOW.value:
            return self.get_group_flow(group_id, name, page_size, page_num, FlowType.WORKFLOW.value)
        elif resource_type.value == ResourceTypeEnum.ASSISTANT.value:
            return self.get_group_assistant(group_id, name, page_size, page_num)
        elif resource_type.value == ResourceTypeEnum.GPTS_TOOL.value:
            return self.get_group_tool(group_id, name, page_size, page_num)
        logger.warning('not support resource type: %s', resource_type)
        return [], 0

    def get_user_map(self, user_ids: set[int]):
        user_list = UserDao.get_user_by_ids(list(user_ids))
        user_map = {user.user_id: user.user_name for user in user_list}
        return user_map

    def get_group_flow(self, group_id: int, keyword: str, page_size: int, page_num: int,flow_type:Optional[int] = None) -> (List[Any], int):
        """ 获取用户组下的知识库列表 """
        # 查询用户组下的技能ID列表
        rs_type = ResourceTypeEnum.FLOW
        if flow_type == FlowType.WORKFLOW.value:
            rs_type = ResourceTypeEnum.WORK_FLOW
        resource_list = GroupResourceDao.get_group_resource(group_id, rs_type)
        if not resource_list:
            return [], 0
        res = []
        flow_ids = [UUID(resource.third_id) for resource in resource_list]
        data, total = FlowDao.filter_flows_by_ids(flow_ids, keyword, page_num, page_size)
        db_user_ids = {one.user_id for one in data}
        user_map = self.get_user_map(db_user_ids)
        for one in data:
            one_dict = jsonable_encoder(one)
            one_dict["user_name"] = user_map.get(one.user_id, one.user_id)
            res.append(one_dict)

        return res, total

    def get_group_knowledge(self, group_id: int, keyword: str, page_size: int, page_num: int) -> (List[Any], int):
        """ 获取用户组下的知识库列表 """
        # 查询用户组下的知识库ID列表
        resource_list = GroupResourceDao.get_group_resource(group_id, ResourceTypeEnum.KNOWLEDGE)
        if not resource_list:
            return [], 0
        res = []
        knowledge_ids = [int(resource.third_id) for resource in resource_list]
        # 查询知识库
        data, total = KnowledgeDao.filter_knowledge_by_ids(knowledge_ids, keyword, page_num, page_size)
        db_user_ids = {one.user_id for one in data}
        user_map = self.get_user_map(db_user_ids)
        for one in data:
            one_dict = jsonable_encoder(one)
            one_dict["user_name"] = user_map.get(one.user_id, one.user_id)
            res.append(one_dict)
        return res, total

    def get_group_assistant(self, group_id: int, keyword: str, page_size: int, page_num: int) -> (List[Any], int):
        """ 获取用户组下的助手列表 """
        # 查询用户组下的助手ID列表
        resource_list = GroupResourceDao.get_group_resource(group_id, ResourceTypeEnum.ASSISTANT)
        if not resource_list:
            return [], 0
        res = []
        assistant_ids = [UUID(resource.third_id) for resource in resource_list]  # 查询助手
        data, total = AssistantDao.filter_assistant_by_id(assistant_ids, keyword, page_num, page_size)
        for one in data:
            simple_one = AssistantService.return_simple_assistant_info(one)
            res.append(simple_one)
        return res, total

    def get_group_tool(self, group_id: int, keyword: str, page_size: int, page_num: int) -> (List[Any], int):
        """ 获取用户组下的工具列表 """
        # 查询用户组下的工具ID列表
        resource_list = GroupResourceDao.get_group_resource(group_id, ResourceTypeEnum.GPTS_TOOL)
        if not resource_list:
            return [], 0
        res = []
        tool_ids = [int(resource.third_id) for resource in resource_list]
        # 查询工具
        data, total = GptsToolsDao.filter_tool_types_by_ids(tool_ids, keyword, page_num, page_size)
        db_user_ids = {one.user_id for one in data}
        user_map = self.get_user_map(db_user_ids)
        for one in data:
            one_dict = jsonable_encoder(one)
            one_dict["user_name"] = user_map.get(one.user_id, one.user_id)
            res.append(one_dict)
        return res, total
