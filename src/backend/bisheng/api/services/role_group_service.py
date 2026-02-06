import asyncio
import json
from datetime import datetime
from typing import List, Any, Dict, Optional

from fastapi import Request, HTTPException
from fastapi.encoders import jsonable_encoder
from loguru import logger

from bisheng.api.services.assistant import AssistantService
from bisheng.api.services.audit_log import AuditLogService
from bisheng.api.v1.schemas import resp_200
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.errcode.user import UserGroupNotDeleteError, AdminUserUpdateForbiddenError
from bisheng.core.cache.redis_manager import get_redis_client_sync
from bisheng.database.constants import AdminRole
from bisheng.database.models.assistant import AssistantDao
from bisheng.database.models.flow import FlowDao, FlowType
from bisheng.database.models.group import Group, GroupCreate, GroupDao, GroupRead, DefaultGroup
from bisheng.database.models.group_resource import GroupResourceDao, ResourceTypeEnum
from bisheng.database.models.role import RoleDao
from bisheng.database.models.user_group import UserGroupCreate, UserGroupDao, UserGroupRead
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao
from bisheng.telemetry_search.domain.services.dashboard import DashboardService
from bisheng.tool.domain.models.gpts_tools import GptsToolsDao
from bisheng.user.domain.models.user import User, UserDao
from bisheng.user.domain.models.user_role import UserRoleDao
from bisheng.utils import get_request_ip


class RoleGroupService():

    def get_group_list(self, group_ids: List[int]) -> List[GroupRead]:
        """Get the full amountgroupVertical"""

        # Inquirygroup
        if group_ids:
            groups = GroupDao.get_group_by_ids(group_ids)
        else:
            groups = GroupDao.get_all_group()
        # Inquiryuser
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
        """Add Usergroup"""
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
        """ New User Group Post Action """
        logger.info(f'act=create_group_hook user={login_user.user_name} group_id={group.id}')
        # Log Audit Logs
        AuditLogService.create_user_group(login_user, get_request_ip(request), group)
        return True

    def update_group(self, request: Request, login_user: UserPayload, group: Group) -> Group:
        """Update User"""
        exist_group = GroupDao.get_user_group(group.id)
        if not exist_group:
            raise ValueError('User group does not exist')
        exist_group.group_name = group.group_name
        exist_group.remark = group.group_name
        exist_group.update_user = login_user.user_id
        exist_group.update_time = datetime.now()

        group = GroupDao.update_group(exist_group)
        self.update_group_hook(request, login_user, group)
        return group

    def update_group_hook(self, request: Request, login_user: UserPayload, group: Group):
        logger.info(f'act=update_group_hook user={login_user.user_name} group_id={group.id}')
        # Log Audit Logs
        AuditLogService.update_user_group(login_user, get_request_ip(request), group)

    def delete_group(self, request: Request, login_user: UserPayload, group_id: int):
        """Can delete existing usergroups"""
        if group_id == DefaultGroup:
            raise HTTPException(status_code=500, detail='Default group cannot be deleted')
        group_info = GroupDao.get_user_group(group_id)
        if not group_info:
            return resp_200()

        # Determine if there are still users in the group
        user_group_list = UserGroupDao.get_group_user(group_id)
        if user_group_list:
            return UserGroupNotDeleteError.return_resp()
        GroupDao.delete_group(group_id)
        self.delete_group_hook(request, login_user, group_info)
        return resp_200()

    def delete_group_hook(self, request: Request, login_user: UserPayload, group_info: Group):
        logger.info(f'act=delete_group_hook user={login_user.user_name} group_id={group_info.id}')
        # Log Audit Logs
        AuditLogService.delete_user_group(login_user, get_request_ip(request), group_info)
        # Move resources under a group to the default user group
        # Get all resources under a group
        all_resource = GroupResourceDao.get_group_all_resource(group_info.id)
        need_move_resource = []
        for one in all_resource:
            # Getting resources belongs to several groups,If you belong to more than one group, you don't have, Otherwise, transfer the resource to the default user group
            resource_groups = GroupResourceDao.get_resource_group(ResourceTypeEnum(one.type), one.third_id)
            if len(resource_groups) > 1:
                continue
            else:
                one.group_id = DefaultGroup
                need_move_resource.append(one)
        if need_move_resource:
            GroupResourceDao.update_group_resource(need_move_resource)
        GroupResourceDao.delete_group_resource_by_group_id(group_info.id)
        # Delete role list under user group
        RoleDao.delete_role_by_group_id(group_info.id)
        # Delete administrators of user groups
        UserGroupDao.delete_group_all_admin(group_info.id)
        # Send delete event toredisQueued
        delete_message = json.dumps({"id": group_info.id})
        redis_client = get_redis_client_sync()
        redis_client.rpush('delete_group', delete_message, expiration=86400)
        redis_client.publish('delete_group', delete_message)

    def get_group_user_list(self, group_id: int, page_size: int, page_num: int) -> List[User]:
        """Get the full amountgroupVertical"""

        # Inquiryuser
        user_group_list = UserGroupDao.get_group_user(group_id, page_size, page_num)
        if user_group_list:
            user_ids = [user.user_id for user in user_group_list]
            return UserDao.get_user_by_ids(user_ids)

        return None

    def insert_user_group(self, user_group: UserGroupCreate) -> UserGroupRead:
        """Insert User Group"""

        user_groups = UserGroupDao.get_user_group(user_group.user_id)
        if user_groups and user_group.group_id in [ug.group_id for ug in user_groups]:
            raise ValueError('Duplicate setup user group')

        return UserGroupDao.insert_user_group(user_group)

    def replace_user_groups(self, request: Request, login_user: UserPayload, user_id: int, group_ids: List[int]):
        """ Overwrite the user group the user belongs to """
        # Determine if the Operated User is a Super Admin
        user_role_list = UserRoleDao.get_user_roles(user_id)
        if any(one.role_id == AdminRole for one in user_role_list):
            raise AdminUserUpdateForbiddenError()

        # Get all previous groupings of users
        old_group = UserGroupDao.get_user_group(user_id)
        old_group = [one.group_id for one in old_group]
        if not login_user.is_admin():
            # Get Operator Managed Groups
            admin_group = UserGroupDao.get_user_admin_group(login_user.user_id)
            admin_group = [one.group_id for one in admin_group]
            # Filter the group where the operator is located, only groups with permission management are processed
            old_group = [one for one in old_group if one in admin_group]
            # Describe this user Not in a user group administered by this user group administrator
            if not old_group:
                raise UnAuthorizedError()
        need_delete_group = old_group.copy()
        need_add_group = []
        for one in group_ids:
            if one not in old_group:
                # User groups to join
                need_add_group.append(one)
            else:
                # Remaining in the old user group is the user group to be moved out
                need_delete_group.remove(one)
        if need_delete_group:
            UserGroupDao.delete_user_groups(user_id, need_delete_group)
        if need_add_group:
            UserGroupDao.add_user_groups(user_id, need_add_group)

        # Log Audit Logs
        group_infos = GroupDao.get_group_by_ids(old_group + group_ids)
        group_dict: Dict[int, str] = {}
        for one in group_infos:
            group_dict[one.id] = one.group_name
        note = "Pre-edit user groups:"
        for one in old_group:
            note += f'{group_dict.get(one, one)}、'
        note = note.rstrip('、')
        note += "Post-edit user groups:"
        for one in group_ids:
            note += f'{group_dict.get(one, one)}、'
        note = note.rstrip('、')
        AuditLogService.update_user(login_user, get_request_ip(request), user_id, list(group_dict.keys()), note)
        return None

    def get_user_groups_list(self, user_id: int) -> List[GroupRead]:
        """Get a list of user groups"""
        user_groups = UserGroupDao.get_user_group(user_id)
        if not user_groups:
            return []
        group_ids = [ug.group_id for ug in user_groups]
        return GroupDao.get_group_by_ids(group_ids)

    def set_group_admin(self, request: Request, login_user: UserPayload, user_ids: List[int], group_id: int):
        """Set up user group administrators"""
        # Get the list of administrators of the current user group
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
            # Users who are not in the group can be assigned as administrators. Do user creation
            for user_id in need_add_admin:
                res.append(UserGroupDao.insert_user_group_admin(user_id, group_id))
        if need_delete_admin:
            UserGroupDao.delete_group_admins(group_id, need_delete_admin)
        # Modified by the most recent modifier for the user group
        GroupDao.update_group_update_user(group_id, login_user.user_id)

        group_info = GroupDao.get_user_group(group_id)
        self.update_group_hook(request, login_user, group_info)
        return res

    def set_group_update_user(self, login_user: UserPayload, group_id: int):
        """Set up user group administrators"""
        GroupDao.update_group_update_user(group_id, login_user.user_id)

    async def get_group_resources(self, group_id: int, resource_type: ResourceTypeEnum, name: str,
                                  page_size: int, page_num: int) -> (List[Any], int):
        """ Get resources under user """
        if resource_type.value == ResourceTypeEnum.FLOW.value:
            return await asyncio.to_thread(self.get_group_flow, group_id, name, page_size, page_num)
        elif resource_type.value == ResourceTypeEnum.KNOWLEDGE.value:
            return await asyncio.to_thread(self.get_group_knowledge, group_id, name, page_size, page_num)
        elif resource_type.value == ResourceTypeEnum.WORK_FLOW.value:
            return await asyncio.to_thread(self.get_group_flow, group_id, name, page_size, page_num, FlowType.WORKFLOW)
        elif resource_type.value == ResourceTypeEnum.ASSISTANT.value:
            return await asyncio.to_thread(self.get_group_assistant, group_id, name, page_size, page_num)
        elif resource_type.value == ResourceTypeEnum.GPTS_TOOL.value:
            return await asyncio.to_thread(self.get_group_tool, group_id, name, page_size, page_num)
        elif resource_type.value == ResourceTypeEnum.DASHBOARD.value:
            return await self.get_group_dashboards(group_id, name, page_size, page_num)
        logger.warning('not support resource type: %s', resource_type)
        return [], 0

    def get_user_map(self, user_ids: set[int]):
        user_list = UserDao.get_user_by_ids(list(user_ids))
        user_map = {user.user_id: user.user_name for user in user_list}
        return user_map

    async def aget_user_map(self, user_ids: set[int]):
        user_list = await UserDao.aget_user_by_ids(list(user_ids))
        user_map = {user.user_id: user.user_name for user in user_list}
        return user_map

    def get_group_flow(self, group_id: int, keyword: str, page_size: int, page_num: int,
                       flow_type: Optional[FlowType] = None) -> (List[Any], int):
        """ Get a list of knowledge bases under user groups """
        # Query skills under user groupsIDVertical
        rs_type = ResourceTypeEnum.FLOW
        if flow_type == FlowType.WORKFLOW:
            rs_type = ResourceTypeEnum.WORK_FLOW
        resource_list = GroupResourceDao.get_group_resource(group_id, rs_type)
        if not resource_list:
            return [], 0
        res = []
        flow_ids = [resource.third_id for resource in resource_list]
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
        """ Get a list of knowledge bases under user groups """
        # Query Knowledge Base under User GroupsIDVertical
        resource_list = GroupResourceDao.get_group_resource(group_id, ResourceTypeEnum.KNOWLEDGE)
        if not resource_list:
            return [], 0
        res = []
        knowledge_ids = [int(resource.third_id) for resource in resource_list]
        # Query Knowledge Base
        data, total = KnowledgeDao.filter_knowledge_by_ids(knowledge_ids, keyword, page_num, page_size)
        db_user_ids = {one.user_id for one in data}
        user_map = self.get_user_map(db_user_ids)
        for one in data:
            one_dict = jsonable_encoder(one)
            one_dict["user_name"] = user_map.get(one.user_id, one.user_id)
            res.append(one_dict)
        return res, total

    def get_group_assistant(self, group_id: int, keyword: str, page_size: int, page_num: int) -> (List[Any], int):
        """ Get a list of helpers under a user group """
        # Query Assistant under User GroupsIDVertical
        resource_list = GroupResourceDao.get_group_resource(group_id, ResourceTypeEnum.ASSISTANT)
        if not resource_list:
            return [], 0
        res = []
        assistant_ids = [resource.third_id for resource in resource_list]  # Query Assistant
        data, total = AssistantDao.filter_assistant_by_id(assistant_ids, keyword, page_num, page_size)
        for one in data:
            simple_one = AssistantService.return_simple_assistant_info(one)
            res.append(simple_one)
        return res, total

    def get_group_tool(self, group_id: int, keyword: str, page_size: int, page_num: int) -> (List[Any], int):
        """ Get a list of tools under user groups """
        # Query Tools under User GroupsIDVertical
        resource_list = GroupResourceDao.get_group_resource(group_id, ResourceTypeEnum.GPTS_TOOL)
        if not resource_list:
            return [], 0
        res = []
        tool_ids = [int(resource.third_id) for resource in resource_list]
        # Query Tools
        data, total = GptsToolsDao.filter_tool_types_by_ids(tool_ids, keyword, page_num, page_size)
        db_user_ids = {one.user_id for one in data}
        user_map = self.get_user_map(db_user_ids)
        for one in data:
            one_dict = jsonable_encoder(one)
            one_dict["user_name"] = user_map.get(one.user_id, one.user_id)
            res.append(one_dict)
        return res, total

    async def get_group_dashboards(self, group_id: int, keyword: str, page_size: int, page_num: int) -> (List[Any],
                                                                                                         int):

        """ Get a list of dashboards under a user group """
        # Query the dashboard under the user groupIDVertical
        resource_list = await GroupResourceDao.aget_group_resources(group_id=group_id,
                                                                    resource_type=ResourceTypeEnum.DASHBOARD)
        if not resource_list:
            return [], 0
        res = []
        dashboard_ids = [int(resource.third_id) for resource in resource_list]
        # Query Dashboard
        data = await DashboardService.get_simple_dashboards(keyword=keyword, filter_ids=dashboard_ids)

        user_map = await self.aget_user_map(set([one.user_id for one in data]))
        for one in data:
            one_dict = one.model_dump(exclude={"layout_config", "style_config"})
            one_dict["name"] = one.title
            one_dict["user_name"] = user_map.get(one.user_id, one.user_id)
            res.append(one_dict)
        if page_size and page_num:
            start_index = (page_num - 1) * page_size
            end_index = start_index + page_size
            paged_res = res[start_index:end_index]
            return paged_res, len(res)
        return res, len(res)

    async def get_manage_resources(self, login_user: UserPayload, keyword: str, page: int, page_size: int) -> (list, int):
        """ Get a list of apps under a user group managed by a user Contains skills, assistants, workflows"""
        groups = []
        if not login_user.is_admin():
            groups = [str(one.group_id) for one in await UserGroupDao.aget_user_admin_group(login_user.user_id)]
            if not groups:
                return [], 0

        resource_ids = []
        # Description is a user group administrator, need to filter to get the resources under the corresponding group
        if groups:
            group_resources = await GroupResourceDao.get_groups_resource(groups, resource_types=[ResourceTypeEnum.FLOW,
                                                                                           ResourceTypeEnum.ASSISTANT,
                                                                                           ResourceTypeEnum.WORK_FLOW])
            if not group_resources:
                return [], 0
            resource_ids = [one.third_id for one in group_resources]

        return await FlowDao.aget_all_apps(keyword, id_list=resource_ids, page=page, limit=page_size)
