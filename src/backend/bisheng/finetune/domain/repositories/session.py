from contextlib import asynccontextmanager

from bisheng.core.context.tenant import strict_tenant_filter
from bisheng.core.database import get_async_db_session


@asynccontextmanager
async def get_finetune_session():
    """Training jobs and credentials belong to the active tenant, not its catalog parent."""
    with strict_tenant_filter():
        async with get_async_db_session() as session:
            yield session
