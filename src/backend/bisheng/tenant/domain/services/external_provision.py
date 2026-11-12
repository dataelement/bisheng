"""专用来源开通不任命管理员, 不分发 Root 资源。"""


class TenantExternalProvisionService:
    def __init__(self, repository, *, anchor_provider, structure_projector=None):
        self.repository = repository
        self.anchor_provider = anchor_provider
        self.structure_projector = structure_projector

    async def ensure(self, command, *, operation):
        receipt = await self.repository.ensure_structure(command, operation, self.anchor_provider)
        # 本专用结构没有 admin/shared_to 关系, 不需要新增权限投影。
        # 若部署另有必要结构关系, 只接受注入的原权限 application 查回适配。
        if self.structure_projector is not None:
            await self.structure_projector(receipt)
        return await self.repository.mark_ready(operation)
