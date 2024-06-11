from typing import List

from bisheng.database.models.group import GroupDao, GroupRead
from bisheng.database.models.group_resource import GroupResourceDao, ResourceTypeEnum
from bisheng.database.models.user import User, UserDao
from bisheng.database.models.user_group import UserGroupCreate, UserGroupDao, UserGroupRead


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
            group.group_admins = ','.join([
                users_dict.get(user.user_id).user_name for user in user_admin
                if user.group_id == group.id
            ])
        return groupReads

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
        ug = []
        if usergroups:
            for user in usergroups:
                user_ids.remove(user.user_id)
                user.is_group_admin = True
            ug.append(UserGroupDao.update_user_groups(usergroups))
        if user_ids:
            # 可以分配非组内用户为管理员。进行用户创建
            for user_id in user_ids:
                ug.append(
                    self.insert_user_group(
                        UserGroupCreate(user_id=user_id, group_id=group_id, is_group_admin=True)))

        return ug

    def get_group_resources(self, group_id: int, resource_type: ResourceTypeEnum, name: str,
                            page_size: int, page_num: int):
        """设置用户组管理员"""
        return GroupResourceDao.get_group_resource(group_id, resource_type, name, page_size,
                                                   page_num)
