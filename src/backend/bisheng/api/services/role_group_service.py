from typing import List

from bisheng.database.models.group import GroupDao, GroupRead
from bisheng.database.models.group_resource import GroupResourceDao, ResourceTypeEnum
from bisheng.database.models.user import UserDao
from bisheng.database.models.user_group import UserGroupCreate, UserGroupDao, UserGroupRead


class RoleGroupService():

    def get_group_list(self) -> List[GroupRead]:
        """获取全量的group列表"""

        groups = GroupDao.get_all_group()
        # 查询user
        user_admin = UserGroupDao.get_groups_admins([group.id for group in groups])
        users_dict = {}
        if user_admin:
            user_ids = [user.user_id for user in user_admin]
            users = UserDao.get_user_by_ids(user_ids)
            users_dict = {user.user_id: user for user in users}

        for group in groups:
            group.group_admins = [
                users_dict.get(user.user_id) for user in user_admin if user.group_id == group.id
            ]
        return groups

    def insert_user_group(self, user_group: UserGroupCreate) -> UserGroupRead:
        """插入用户组"""

        user_groups = UserGroupDao.get_user_group(user_group.user_id)
        if user_groups and user_group.group_id in [ug.group_id for ug in user_groups]:
            raise ValueError('重复设置用户组')

        return UserGroupDao.insert_user_group(user_group)

    def get_user_groups_list(self, user_id: int) -> List[GroupRead]:
        """获取用户组列表"""
        user_groups = UserGroupDao.get_user_group(user_id)
        if not user_groups:
            return []
        group_ids = [ug.group_id for ug in user_groups]
        return GroupDao.get_group_by_ids(group_ids)

    def set_group_admin(self, user_ids: List[int], group_id: int):
        """设置用户组管理员"""
        usergroups = UserGroupDao.is_users_in_group(group_id, user_ids)
        if usergroups:
            # 只能设置组内的人为管理员
            for user in usergroups:
                user.is_group_admin = True
            return UserGroupDao.update_user_groups(usergroups)
        else:
            return None

    def get_group_resources(self, group_id: int, resource_type: ResourceTypeEnum):
        """设置用户组管理员"""
        return GroupResourceDao.get_group_resource(group_id, resource_type)
