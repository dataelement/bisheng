"""ORM usage metrics in an already-verified execution tenant; unknown is not 0."""

from contextlib import nullcontext
from datetime import datetime

from loguru import logger
from sqlalchemy import func
from sqlmodel import select

from bisheng.common.errcode.tenant_quota import QuotaUsageUnavailableError
from bisheng.core.context.tenant import bypass_tenant_filter, strict_tenant_filter, tenant_execution_scope
from bisheng.core.database import get_async_db_session
from bisheng.core.database.dialect_helpers import StrJoinKey


def usage_statement(resource_type: str, tenant_id: int, user_id: int | None = None):
    # Metric models are imported lazily to keep the public policy reader's
    # import graph small. Tenant equality is additionally explicit for joins:
    # automatic entity discovery cannot prove the scope of every joined COUNT.
    from bisheng.channel.domain.models.channel import Channel
    from bisheng.common.models.space_channel_member import (
        BusinessTypeEnum,
        MembershipStatusEnum,
        SpaceChannelMember,
        UserRoleEnum,
    )
    from bisheng.database.models.flow import Flow
    from bisheng.database.models.tenant import UserTenant
    from bisheng.knowledge.domain.models.department_knowledge_space import DepartmentKnowledgeSpace
    from bisheng.knowledge.domain.models.knowledge import Knowledge, _personal_space_quota_count_predicate
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
    from bisheng.llm.domain.models.llm_token_log import LLMTokenLog
    from bisheng.tool.domain.models.gpts_tools import GptsTools
    from bisheng.user.domain.models.user import User

    conditions = []
    if resource_type in ("workflow", "assistant", "dashboard"):
        model = Flow
        conditions = [
            Flow.flow_type == {"workflow": 10, "assistant": 5, "dashboard": 15}[resource_type],
            Flow.status != 0,
        ]
        if resource_type == "workflow":
            conditions.append(Flow.is_delete == 0)
    elif resource_type == "tool":
        model, conditions = GptsTools, [GptsTools.is_delete == 0]
    elif resource_type == "channel":
        model = Channel
    elif resource_type == "knowledge_space":
        model, conditions = Knowledge, [Knowledge.type == 3]
        if user_id is not None:
            conditions.append(_personal_space_quota_count_predicate())
            conditions.append(
                ~select(DepartmentKnowledgeSpace.id).where(DepartmentKnowledgeSpace.space_id == Knowledge.id).exists()
            )
    elif resource_type in ("storage_gb", "knowledge_space_file"):
        statement = select(func.coalesce(func.sum(KnowledgeFile.file_size), 0)).where(
            KnowledgeFile.tenant_id == tenant_id, KnowledgeFile.file_source.in_(["channel", "space_upload"])
        )
        return statement.where(KnowledgeFile.user_id == user_id) if user_id is not None else statement
    elif resource_type in ("channel_subscribe", "knowledge_space_subscribe"):
        parent = Channel if resource_type == "channel_subscribe" else Knowledge
        statement = (
            select(func.count(SpaceChannelMember.id))
            .join(parent, StrJoinKey(parent.id) == SpaceChannelMember.business_id)
            .where(
                # A Root subscription is still an account subscription for a
                # child, not a newly created child resource. Other children
                # must not consume the new home's personal budget.
                parent.tenant_id.in_({tenant_id, 1} if user_id is not None else {tenant_id}),
                SpaceChannelMember.business_type
                == (BusinessTypeEnum.CHANNEL if parent is Channel else BusinessTypeEnum.SPACE),
                SpaceChannelMember.user_role.in_([UserRoleEnum.MEMBER, UserRoleEnum.ADMIN]),
                SpaceChannelMember.status.in_([MembershipStatusEnum.ACTIVE, MembershipStatusEnum.PENDING]),
            )
        )
        return statement.where(SpaceChannelMember.user_id == user_id) if user_id is not None else statement
    elif resource_type == "user_count":
        return (
            select(func.count(func.distinct(UserTenant.user_id)))
            .join(User, User.user_id == UserTenant.user_id)
            .where(
                UserTenant.tenant_id == tenant_id,
                UserTenant.is_active == 1,
                UserTenant.status == "active",
                User.delete == 0,
            )
        )
    elif resource_type == "model_tokens_monthly":
        statement = select(func.coalesce(func.sum(LLMTokenLog.total_tokens), 0)).where(
            LLMTokenLog.tenant_id == tenant_id,
            LLMTokenLog.created_at >= datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0),
        )
        return statement.where(LLMTokenLog.user_id == user_id) if user_id is not None else statement
    else:
        raise ValueError("Unknown quota metric")
    conditions.append(model.tenant_id == tenant_id)
    if user_id is not None:
        conditions.append(model.user_id == user_id)
    return select(func.count()).select_from(model).where(*conditions)


class QuotaRepository:
    @staticmethod
    async def count(tenant_id: int, resource_type: str, *, user_id: int | None = None) -> int | float:
        if resource_type == "info_source_subscribe":
            return len(await QuotaRepository.source_ids(tenant_id, user_id=user_id))
        try:
            statement = usage_statement(resource_type, tenant_id, user_id)
            with tenant_execution_scope(tenant_id), strict_tenant_filter():
                shared_subscription = user_id is not None and resource_type in (
                    "channel_subscribe",
                    "knowledge_space_subscribe",
                )
                with bypass_tenant_filter() if shared_subscription else nullcontext():
                    async with get_async_db_session() as session:
                        value = (await session.exec(statement)).one()
            if resource_type in ("storage_gb", "knowledge_space_file"):
                return float(value or 0) / (1024**3)
            return int(value or 0)
        except Exception as exc:
            logger.exception("Quota usage is unknown: tenant={} metric={}", tenant_id, resource_type)
            raise QuotaUsageUnavailableError(resource_type=resource_type, usage_state="UNAVAILABLE") from exc

    @staticmethod
    async def source_ids(tenant_id: int, *, user_id: int | None = None) -> set[str]:
        from bisheng.channel.domain.models.channel import Channel

        try:
            statement = select(Channel.source_list).where(Channel.tenant_id == tenant_id)
            if user_id is not None:
                statement = statement.where(Channel.user_id == user_id)
            with tenant_execution_scope(tenant_id), strict_tenant_filter():
                async with get_async_db_session() as session:
                    rows = (await session.exec(statement)).all()
            return {source_id for values in rows for source_id in (values or [])}
        except Exception as exc:
            logger.exception("Source usage is unknown: tenant={} user={}", tenant_id, user_id)
            raise QuotaUsageUnavailableError(resource_type="info_source_subscribe", usage_state="UNAVAILABLE") from exc
