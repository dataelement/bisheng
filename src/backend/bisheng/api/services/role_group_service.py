from typing import List

from bisheng.database.models.group import GroupDao, GroupRead


class RoleGroupService():

    def get_group_list(self) -> List[GroupRead]:
        """获取全量的group列表"""

        groups = GroupDao.get_all_group()

        return groups
