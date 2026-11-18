"""Read the actual children inheriting each Root system-model section."""

from sqlalchemy import select

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.database.models.tenant import ROOT_TENANT_ID, Tenant
from bisheng.llm.domain.models.tenant_system_model_config import TenantSystemModelConfig


async def inheriting_children(session, keys):
    with bypass_tenant_filter():
        root = await session.get(Tenant, ROOT_TENANT_ID)
        if root is None or not root.share_default_to_children:
            return dict.fromkeys(keys, ())
        children = tuple(
            (
                await session.execute(
                    select(Tenant.id).where(Tenant.parent_tenant_id == ROOT_TENANT_ID, Tenant.status == "active")
                )
            ).scalars()
        )
        overrides = (
            (
                await session.execute(
                    select(TenantSystemModelConfig.tenant_id, TenantSystemModelConfig.key).where(
                        TenantSystemModelConfig.tenant_id.in_(children),
                        TenantSystemModelConfig.key.in_(keys),
                        TenantSystemModelConfig.value.is_not(None),
                        TenantSystemModelConfig.value != "",
                    )
                )
            ).all()
            if children
            else ()
        )
    local = set(overrides)
    return {key: tuple(child for child in children if (child, key) not in local) for key in keys}
