from abc import ABC
from bisheng.common.repositories.interfaces.base_repository import BaseRepository
from bisheng.user.domain.models.user import User, UserQuery


class UserRepository(BaseRepository[User, int], ABC):
    """用户仓库接口类"""

    # 根据user_id获取用户信息 user、user_groups、roles
    async def get_user_with_groups_and_roles_by_user_id(self, user_id: int) -> UserQuery:
        pass

    def get_user_with_groups_and_roles_by_user_id_sync(self, user_id: int) -> UserQuery:
        pass
