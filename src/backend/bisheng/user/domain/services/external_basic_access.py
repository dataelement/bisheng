"""基础资格业务入口, 不产生通用创建权或资源授权。"""


class UserExternalBasicAccessService:
    def __init__(self, repository):
        self.repository = repository

    async def ensure(self, command, *, operation):
        return await self.repository.apply(command, operation)
