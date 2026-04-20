"""F012 GET /api/v1/user/current-tenant handler — extracted from user.py.

Living in a narrowly-scoped module so unit tests can import and execute
the handler without pulling in the full ``bisheng.user.api.user`` chain
(which transitively imports ``bisheng.api.services.*``, causing cascade
import failures under the conftest pre-mocking used by tests).
"""

from __future__ import annotations

import logging

from sqlmodel import select

from bisheng.common.schemas.api import resp_200
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.database.models.department import Department
from bisheng.database.models.tenant import ROOT_TENANT_ID
from bisheng.tenant.domain.services.tenant_resolver import TenantResolver

logger = logging.getLogger(__name__)


async def get_current_tenant_handler(login_user) -> object:
    """Resolve the caller's leaf tenant and shape the AC-10 response.

    Returns a ``UnifiedResponseModel`` via ``resp_200`` with payload:
    ``{leaf_tenant_id, is_child, mounted_department_id, root_tenant_id}``.
    """
    leaf = await TenantResolver.resolve_user_leaf_tenant(login_user.user_id)
    is_child = (
        getattr(leaf, 'parent_tenant_id', None) is not None
        and leaf.id != ROOT_TENANT_ID
    )
    mounted_department_id = None
    root_tenant_id = ROOT_TENANT_ID

    if is_child:
        try:
            with bypass_tenant_filter():
                async with get_async_db_session() as session:
                    result = await session.exec(
                        select(Department.id).where(
                            Department.mounted_tenant_id == leaf.id,
                        ).limit(1)
                    )
                    row = result.first()
                    if row is not None:
                        mounted_department_id = int(row)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                'mounted dept lookup failed for tenant %s: %s', leaf.id, exc,
            )
        root_tenant_id = getattr(leaf, 'parent_tenant_id', ROOT_TENANT_ID)

    return resp_200({
        'leaf_tenant_id': leaf.id,
        'is_child': is_child,
        'mounted_department_id': mounted_department_id,
        'root_tenant_id': root_tenant_id,
    })
