"""积分 API 依赖注入。"""

from fastapi import Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.dependencies.core_deps import get_db_session
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.core.context.tenant import DEFAULT_TENANT_ID, get_current_tenant_id
from bisheng.message.api.dependencies import get_message_service
from bisheng.points.domain.repositories.points_repository import PointsRepository
from bisheng.points.domain.services.points_ledger_service import PointsLedgerService
from bisheng.points.domain.services.points_notify_service import PointsNotifyService
from bisheng.points.domain.services.points_query_service import PointsQueryService
from bisheng.points.domain.services.points_rule_service import PointsRuleService


def get_login_user(user: UserPayload = Depends(UserPayload.get_login_user)) -> UserPayload:
    """统一暴露当前已登录用户。"""
    return user


def resolve_tenant_id(user: UserPayload) -> int:
    """解析当前请求租户；优先中间件注入的 tenant context。"""
    return int(get_current_tenant_id() or user.tenant_id or DEFAULT_TENANT_ID)


async def get_points_repository(
    session: AsyncSession = Depends(get_db_session),
) -> PointsRepository:
    """提供积分仓储。"""
    return PointsRepository(session)


async def get_points_notify_service(
    message_service=Depends(get_message_service),
) -> PointsNotifyService:
    """提供积分站内信服务。"""
    return PointsNotifyService(message_service=message_service)


async def get_points_ledger_service(
    repository: PointsRepository = Depends(get_points_repository),
    notify: PointsNotifyService = Depends(get_points_notify_service),
) -> PointsLedgerService:
    """提供账本服务。"""
    return PointsLedgerService(repository, notify_service=notify)


async def get_points_query_service(
    session: AsyncSession = Depends(get_db_session),
    repository: PointsRepository = Depends(get_points_repository),
    ledger: PointsLedgerService = Depends(get_points_ledger_service),
    notify: PointsNotifyService = Depends(get_points_notify_service),
) -> PointsQueryService:
    """提供查询与管理端调分服务。"""
    return PointsQueryService(session, repository, ledger, notify)


async def get_points_rule_service(
    session: AsyncSession = Depends(get_db_session),
    repository: PointsRepository = Depends(get_points_repository),
) -> PointsRuleService:
    """提供规则与文案服务。"""
    return PointsRuleService(session, repository)
