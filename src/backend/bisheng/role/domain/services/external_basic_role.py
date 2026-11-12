"""角色业务协议不包含 SQL 或外部权限调用。"""


class RoleExternalBasicRoleService:
    def __init__(self, repository):
        self.repository = repository

    async def ensure(self, operation):
        return await self.repository.apply(operation)
