from fastapi import Request
from pydantic import BaseModel

from bisheng.api.errcode.base import NotFoundError, UnAuthorizedError
from bisheng.api.services.user_service import UserPayload
from bisheng.database.models.role import RoleCreate, Role, RoleDao, RoleUpdate, RoleRead
from bisheng.database.models.user import UserDao
from bisheng.database.models.user_role import UserRoleDao


class RoleService(BaseModel):

    request: Request
    login_user: UserPayload

    class Config:
        arbitrary_types_allowed = True

    def add_role(self, data: RoleCreate):
        if not data.group_id or not data.role_name:
            raise NotFoundError.http_exception('用户组ID或角色名不能为空')
        if not self.login_user.check_group_admin(data.group_id):
            raise UnAuthorizedError.http_exception()

        db_role = RoleDao.insert_role(Role.validate(data))
        # 需要建立角色和用户的关联
        if not db_role.is_bind_all:
            if data.user_ids:
                UserRoleDao.add_role_users(db_role.id, data.user_ids)
        return db_role

    def update_role(self, role_id: int, data: RoleUpdate):
        db_role = RoleDao.get_role_by_id(role_id)
        if not db_role:
            raise NotFoundError.http_exception()
        if not self.login_user.check_group_admin(db_role.group_id):
            raise UnAuthorizedError.http_exception()
        # 是否变更过绑定关系
        bind_change = db_role.is_bind_all != data.is_bind_all
        if data.role_name:
            db_role.role_name = data.role_name
        db_role.remark = data.remark
        db_role.extra = data.extra
        db_role.is_bind_all = data.is_bind_all

        # 更新角色信息
        db_role = RoleDao.update_role(db_role)

        if db_role.is_bind_all and bind_change:
            # 清理这个角色之前的绑定关系
            UserRoleDao.delete_role_users(db_role.id)
        elif not db_role.is_bind_all:
            # 清理这个角色之前的绑定关系
            UserRoleDao.delete_role_users(db_role.id)
            if not db_role.is_bind_all and data.user_ids:
                # 重新建立角色和用户的关联
                UserRoleDao.add_role_users(db_role.id, data.user_ids)
        return db_role

    def get_role_info(self, role_id: int) -> RoleCreate:
        db_role = RoleDao.get_role_by_id(role_id)
        if not db_role:
            raise NotFoundError.http_exception()
        if not self.login_user.check_group_admin(db_role.group_id):
            raise UnAuthorizedError.http_exception()
        res = RoleRead.validate(db_role)

        # 获取角色绑定的用户列表
        if not res.is_bind_all:
            users = [one.user_id for one in UserRoleDao.get_roles_user([role_id])]
            users = UserDao.get_user_by_ids(users)
            res.user_ids = [{
                'user_id': one.user_id,
                'user_name': one.user_name
            } for one in users]
        return res
