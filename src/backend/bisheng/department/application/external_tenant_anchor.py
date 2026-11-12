"""跨领域只传受控事务及结构参数, 不导出部门 ORM。"""

from bisheng.department.domain.repositories.external_tenant_anchor import ExternalTenantAnchorRepository


async def ensure_external_tenant_anchor(session, **kwargs) -> int:
    return await ExternalTenantAnchorRepository.ensure(session, **kwargs)
