import json
from datetime import datetime
from typing import List, Any, Dict, Optional
from uuid import UUID

from fastapi import Request, HTTPException
from fastapi.encoders import jsonable_encoder
from loguru import logger

from bisheng.api.errcode.base import NotFoundError, UnAuthorizedError
from bisheng.api.errcode.user import UserGroupNotDeleteError, UserGroupSubGroupError
from bisheng.api.services.assistant import AssistantService
from bisheng.api.services.audit_log import AuditLogService
from bisheng.api.services.user_service import UserPayload
from bisheng.api.utils import get_request_ip
from bisheng.api.v1.schemas import resp_200
from bisheng.cache.redis import redis_client
from bisheng.database.models.assistant import AssistantDao
from bisheng.database.models.flow import FlowDao, FlowType
from bisheng.database.models.gpts_tools import GptsToolsDao
from bisheng.database.models.group import Group, GroupCreate, GroupDao, GroupRead, DefaultGroup
from bisheng.database.models.group_resource import GroupResourceDao, ResourceTypeEnum
from bisheng.database.models.knowledge import KnowledgeDao
from bisheng.database.models.role import AdminRole, RoleDao
from bisheng.database.models.user import User, UserDao
from bisheng.database.models.user_group import UserGroupCreate, UserGroupDao, UserGroupRead
from bisheng.database.models.user_role import UserRoleDao


class RoleGroupService():

    @staticmethod
    def get_all_group_tree():
        # 先查出所有的用户组
        groups = GroupDao.get_all_group()
        # 转化为字典 id: group
        groups_dict = {}
        # 转化为树结构 level: {id: group}
        group_tree = {}
        for one in groups:
            groups_dict[one.id] = GroupRead(**one.model_dump())
            if one.level not in group_tree:
                group_tree[one.level] = {}
            group_tree[one.level][one.id] = groups_dict[one.id]
        return groups_dict, group_tree

    def get_group_list(self, group_ids: List[int]) -> List[GroupRead]:
        """获取全量的group列表"""
        groups_dict, group_tree = self.get_all_group_tree()

        # 非超管过滤只属于他管理的group和其子用户组
        if group_ids:
            tmp_group_dict = {}
            for group_id in group_ids:
                if group_id not in groups_dict:
                    continue
                tmp_group_dict[group_id] = groups_dict[group_id]
                tmp_group_dict.update(self.get_child_groups(groups_dict[group_id], group_tree))
            groups_dict = tmp_group_dict

        # 查询user
        user_admin = UserGroupDao.get_groups_admins(list(groups_dict.keys()))
        users_dict = {}
        if user_admin:
            user_ids = [user.user_id for user in user_admin]
            users = UserDao.get_user_by_ids(user_ids)
            users_dict = {user.user_id: user for user in users}

        for group in groups_dict.values():
            group.group_admins = [
                users_dict.get(user.user_id).model_dump() for user in user_admin
                if user.group_id == group.id
            ]
            group.parent_group_path = self.get_parent_group_path(group, group_tree)
        return list(groups_dict.values())

    def get_all_children(self, group: GroupRead, group_tree: dict, max_level: int = None):
        # 获取直系子用户组
        children = list(self.get_child_groups(group, group_tree, group.level + 1).values())
        if not children:
            return []
        for child in children:
            child.children = self.get_all_children(child, group_tree, child.level + 1)
        return children

    def get_group_tree(self, group_ids) -> List[GroupRead]:
        group_dict, group_tree = self.get_all_group_tree()
        res = []
        if not group_tree:
            return []
        # 转为数结构
        for one in group_tree[0].values():
            one.children = self.get_all_children(one, group_tree, max_level=one.level + 1)
            if not group_ids:
                res.append(one)
                continue

            # 非超管过滤只属于他管理的group和其子用户组
            res.extend(self.filter_groups_tree(one, group_ids))
        return res

    def filter_groups_tree(self, one, group_ids):
        if one.id in group_ids:
            return [one]
        if not one.children:
            return []

        # 遍历子用户组是否在group_ids中
        res = []
        for child in one.children:
            child_res = self.filter_groups_tree(child, group_ids)
            res.extend(child_res)
        return res

    @staticmethod
    def get_parent_group_path(group: GroupRead, group_tree: dict):
        """ 获取用户组的父级路径 """
        level = group.level
        parent_groups = []
        while level > 0:
            parent_group = group_tree[level - 1][group.parent_id]
            parent_groups.append(parent_group.group_name)
            group = parent_group
            level -= 1
        parent_groups = parent_groups[::-1]
        return '/'.join(parent_groups)

    def get_child_groups(self, group: GroupRead, group_tree: dict, max_level: int = None):
        """ 获取所有的子用户组 """
        child_group = {}
        level = group.level + 1
        if max_level and level > max_level:
            return child_group
        if group_tree.get(level):
            for _, group_info in group_tree[level].items():
                if group_info.parent_id == group.id:
                    child_group[group_info.id] = group_info
            for _, group_info in child_group.items():
                child_group.update(self.get_child_groups(group_info, group_tree, max_level))
        return child_group

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
        groups = [group_id]
        child_group = GroupDao.get_child_groups(group_info.code)
        groups.extend([one.id for one in child_group])
        # 判断组下以及子用户组下是否还有用户
        user_group_list = UserGroupDao.get_groups_user(groups)
        if user_group_list:
            return UserGroupNotDeleteError.return_resp()
        GroupDao.delete_groups(groups)
        logger.info(f'act=delete_sub_group user={login_user.user_name} group_id={group_info.id} sub_group={child_group}')
        for one in child_group:
            self.delete_group_hook(request, login_user, one)
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
        redis_client.rpush('delete_group', delete_message, expiration=86400)
        redis_client.publish('delete_group', delete_message)

    def get_group_user_list(self, group_id: int, page: int, limit: int) -> (List[User], int):
        """获取全量的group列表"""

        group_info = GroupDao.get_user_group(group_id)
        if not group_info:
            raise NotFoundError.http_exception()
        # 获取所有的子用户组
        child_group = GroupDao.get_child_groups(group_info.code)
        group_ids = [group.id for group in child_group]
        group_ids.append(group_id)

        # 查询user
        users_groups = UserGroupDao.get_groups_users(group_ids, page, limit)
        if len(users_groups) == 0:
            return [], 0
        user_ids = set()
        user_group_dict = {}
        for one in users_groups:
            user_ids.add(one.user_id)
            if one.user_id not in user_group_dict:
                user_group_dict[one.user_id] = set()
            user_group_dict[one.user_id].add(one.group_id)

        total = UserGroupDao.count_groups_user(group_ids)
        user_list = UserDao.get_user_by_ids(list(user_ids))
        res = []
        for one in user_list:
            user_info = one.model_dump()
            user_info['group_ids'] = list(user_group_dict.get(one.user_id, []))
            res.append(user_info)
        return res, total


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
            return self.get_group_flow(group_id, name, page_size, page_num, FlowType.WORKFLOW)
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

    def get_group_flow(self, group_id: int, keyword: str, page_size: int, page_num: int,
                       flow_type: Optional[FlowType] = None) -> (List[Any], int):
        """ 获取用户组下的知识库列表 """
        # 查询用户组下的技能ID列表
        rs_type = ResourceTypeEnum.FLOW
        if flow_type == FlowType.WORKFLOW:
            rs_type = ResourceTypeEnum.WORK_FLOW
        resource_list = GroupResourceDao.get_group_resource(group_id, rs_type)
        if not resource_list:
            return [], 0
        res = []
        flow_ids = [UUID(resource.third_id) for resource in resource_list]
        flow_type_value = flow_type.value if flow_type else FlowType.FLOW.value
        data, total = FlowDao.filter_flows_by_ids(flow_ids, keyword, page_num, page_size, flow_type_value)
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

    def get_manage_resources(self, request: Request, login_user: UserPayload, keyword: str, page: int,
                             page_size: int) -> (list, int):
        """ 获取用户所管理的用户组下的应用列表 包含技能、助手、工作流"""
        groups = []
        if not login_user.is_admin():
            groups = [str(one.group_id) for one in UserGroupDao.get_user_admin_group(login_user.user_id)]
            if not groups:
                return [], 0

        resource_ids = []
        # 说明是用户组管理员，需要过滤获取到对应组下的资源
        if groups:
            group_resources = GroupResourceDao.get_groups_resource(groups, resource_types=[ResourceTypeEnum.FLOW,
                                                                                           ResourceTypeEnum.ASSISTANT,
                                                                                           ResourceTypeEnum.WORK_FLOW])
            if not group_resources:
                return [], 0
            resource_ids = [one.third_id for one in group_resources]

        return FlowDao.get_all_apps(keyword, id_list=resource_ids, page=page, limit=page_size)

    def get_group_roles(self, login_user: UserPayload, group_ids: List[int], keyword: str, page: int, page_size: int,
                        include_parent: bool) -> (list, int):

        """获取用户组下的角色列表"""
        # 判断是否是超级管理员
        if login_user.is_admin():
            # 是超级管理员获取全部
            group_ids = group_ids
        else:
            # 查询下是否是其他用户组的管理员
            user_groups = UserGroupDao.get_user_admin_group(login_user.user_id)
            user_group_ids = [one.group_id for one in user_groups if one.is_group_admin]
            if group_ids:
                group_ids = list(set(group_ids) & set(user_group_ids))
            else:
                group_ids = user_group_ids
            if not group_ids:
                raise HTTPException(status_code=500, detail='无查看权限')

        # 查询属于当前组的角色列表，以及父用户组绑定的角色列表
        role_list = RoleDao.get_role_by_groups(group_ids, keyword, page, page_size, include_parent)
        total = RoleDao.count_role_by_groups(group_ids, keyword, include_parent=include_parent)
        return role_list, total

    def get_user_group_roles(self, login_user: UserPayload, user_id: int, group_id: int):
        """ 获取用户在用户组下的角色列表 """
        user_roles = UserRoleDao.get_user_roles(user_id)
        roles_info = RoleDao.get_role_by_ids([one.role_id for one in user_roles])
        role_list = RoleDao.get_role_by_groups([group_id], include_parent=True, only_bind=True)
        res = {one.id: one for one in roles_info}
        for one in role_list:
            if one.id not in res:
                res[one.id] = one
        return list(res.values())

    def sync_third_groups(self, data: List[Dict]):
        """ 同步第三方部门数据 """
        logger.debug('sync_third_groups start')
        root_group = data[0]
        # 更新根用户组的信息
        default_group = GroupDao.get_user_group(DefaultGroup)
        if default_group.group_name != root_group['name']:
            default_group.group_name = root_group['name']
            default_group.third_id = root_group['id']
            GroupDao.update_group(default_group)
        logger.debug("start sync update group info")
        user_groups = self.sync_one_group(root_group, None)
        logger.debug("start sync user group change")
        for user_id, new_group_ids in user_groups.items():
            # 获取用户所属的用户组
            old_group_ids = {one.group_id for one in UserGroupDao.get_user_group(user_id)}

            # 将用户放到这些用户组内
            need_add_groups = new_group_ids - old_group_ids
            if need_add_groups:
                logger.debug(f'add_user_groups user_id: {user_id} groups: {need_add_groups}')
                UserGroupDao.add_user_groups(user_id, list(need_add_groups))
            need_remove_groups = old_group_ids - new_group_ids
            if need_remove_groups:
                logger.debug(f'remove_user_groups user_id: {user_id} groups: {need_remove_groups}')
                UserGroupDao.delete_user_groups(user_id, list(need_remove_groups))
        logger.debug('sync_third_groups over')

    def sync_one_group(self, department: Dict, parent_group: Group = None):
        """ 同步一个用户组数据
        department: 第三方的部门数据， 目前指企微
        group: 对应的毕昇里的用户组
         """
        group = self.update_group_data(department, parent_group)

        # user_id: [group is list]
        user_groups = {}
        self.update_department_user(department, group, user_groups)

        if not department.get('children', None):
            return user_groups
        for one in department['children']:
            child_user_groups = self.sync_one_group(one, group)
            for user_id, group_ids in child_user_groups.items():
                if user_id not in user_groups:
                    user_groups[user_id] = group_ids
                else:
                    user_groups[user_id] = user_groups[user_id] | group_ids
        return user_groups

    def update_department_user(self, department: Dict, group: Group, user_group: Dict):
        for one in department['users']:
            user = UserDao.get_user_by_username(one['userId'])
            if not user:
                user = UserDao.create_user(User(
                    user_name=one['userId'],
                    password=''
                ))
            if user.user_id not in user_group:
                user_group[user.user_id] = set()
            user_group[user.user_id].add(group.id)

    def update_group_data(self, department: Dict, parent_group: Group = None):
        """ 跟新分组的数据 """
        group = GroupDao.get_group_by_third_id(department['id'])
        # 没有对应的group先新建
        if not group:
            group = Group(
                group_name=department['name'],
                third_id=department['id'],
                create_user=1,
            )
            if parent_group:
                group.parent_id = parent_group.id
            try:
                group = GroupDao.insert_group(group)
            except:
                logger.error(f'insert group error: {group}')
                group.group_name = f'{group.group_name}（部门ID：{group.third_id}）'
                group = GroupDao.insert_group(group)
            return group
        else:
            if group.group_name != department['name']:
                # 更新部门的名称
                group.group_name = department['name']
                try:
                    group = GroupDao.update_group(group)
                except:
                    logger.error(f'update group error: {group}')
                    group.group_name = f'{group.group_name}（部门ID：{group.third_id}）'
                    group = GroupDao.update_group(group)
        # 说明父部门发生变更，修改部门的父部门
        if parent_group and group.parent_id != parent_group.id:
            # 清理组下用户和父部门角色的关系
            old_parent_groups = [one.id for one in GroupDao.get_parent_groups(group.code)]
            group = GroupDao.update_parent_group(group, parent_group)
            new_parent_groups = [one.id for one in GroupDao.get_parent_groups(group.code)]

            # 现在从哪些父部门移出去了
            remove_parent_groups = list(set(old_parent_groups) - set(new_parent_groups))
            if remove_parent_groups:
                need_remove_roles = [one.id for one in RoleDao.get_role_by_groups(remove_parent_groups)]
                # 获取用户组下所有的用户
                sub_groups = [one.id for one in GroupDao.get_child_groups(group.code)]
                sub_groups.append(group.id)
                group_all_user = UserGroupDao.get_groups_user(sub_groups)
                if group_all_user and need_remove_roles:
                    UserRoleDao.delete_users_roles(group_all_user, need_remove_roles)
        return group

