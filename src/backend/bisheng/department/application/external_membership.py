"""昆联成员复用已有部门 SQL 与持久权限投影, 不开放公共写入口。"""

from loguru import logger

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.sso_sync import KunlianDependencyUnavailableError, KunlianError
from bisheng.core.context.tenant import strict_tenant_filter, tenant_execution_scope
from bisheng.department.domain.services.department_service import DepartmentMembershipProjectionService


async def ensure_external_department_membership(user_id, local_tenant_id, root_department_id):
    try:
        # 租户挂载节点归 Root 管理; 写入前仍在部门事务内核验实际目标。
        with tenant_execution_scope(1), strict_tenant_filter():
            await DepartmentMembershipProjectionService.aadd_member(
                user_id=user_id,
                department_id=root_department_id,
                is_primary=1,
                source="kunlian",
                external_tenant_id=local_tenant_id,
            )
    except KunlianError:
        raise
    except BaseErrorCode as exc:
        logger.warning("Kunlian department membership projection unavailable code={}", exc.code)
        raise KunlianDependencyUnavailableError() from exc
