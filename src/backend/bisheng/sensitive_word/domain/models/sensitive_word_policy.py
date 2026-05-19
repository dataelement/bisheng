from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import Boolean, Column, DateTime, Integer, String, UniqueConstraint, text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Field, select

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_async_db_session, get_sync_db_session
from bisheng.core.database.dialect_helpers import JsonType, LargeText


class SensitiveWordPolicyBase(SQLModelSerializable):
    tenant_id: int = Field(
        sa_column=Column(Integer, nullable=False, index=True, comment='租户ID'),
    )
    business_type: str = Field(
        sa_column=Column(String(64), nullable=False, index=True, comment='业务场景'),
    )
    scope_type: str = Field(
        default='tenant',
        sa_column=Column(String(32), nullable=False, server_default=text("'tenant'"), comment='作用域类型'),
    )
    scope_id: str = Field(
        sa_column=Column(String(64), nullable=False, index=True, comment='作用域ID'),
    )
    enabled: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=text('0'), comment='是否启用'),
    )
    words_types: List[str] = Field(
        default_factory=list,
        sa_column=Column(JsonType, nullable=True, comment='词表类型：builtin/custom'),
    )
    custom_words: str = Field(
        default='',
        sa_column=Column(LargeText, nullable=False, comment='自定义词表内容'),
    )
    auto_reply: str = Field(
        default='',
        sa_column=Column(String(500), nullable=False, server_default=text("''"), comment='命中提示话术'),
    )
    extra_config: Dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JsonType, nullable=True, comment='扩展配置'),
    )
    created_by: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=True, comment='创建人ID'))
    updated_by: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=True, comment='更新人ID'))
    create_time: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')),
    )
    update_time: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=text('CURRENT_TIMESTAMP'),
            onupdate=text('CURRENT_TIMESTAMP'),
        ),
    )
    logic_delete: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default=text('0'), comment='逻辑删除标记'),
    )


class SensitiveWordPolicy(SensitiveWordPolicyBase, table=True):
    __tablename__ = 'sensitive_word_policy'
    __table_args__ = (
        UniqueConstraint(
            'tenant_id',
            'business_type',
            'scope_type',
            'scope_id',
            'logic_delete',
            name='uk_sensitive_policy_scope',
        ),
        {'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci'},
    )

    id: Optional[int] = Field(default=None, primary_key=True)


class SensitiveWordPolicyDao:
    @classmethod
    def _scope_stmt(
        cls,
        tenant_id: int,
        business_type: str,
        scope_type: str = 'tenant',
        scope_id: Optional[str] = None,
    ):
        return select(SensitiveWordPolicy).where(
            SensitiveWordPolicy.tenant_id == tenant_id,
            SensitiveWordPolicy.business_type == business_type,
            SensitiveWordPolicy.scope_type == scope_type,
            SensitiveWordPolicy.scope_id == (scope_id or str(tenant_id)),
            SensitiveWordPolicy.logic_delete == 0,
        )

    @classmethod
    def get_policy(
        cls,
        tenant_id: int,
        business_type: str,
        scope_type: str = 'tenant',
        scope_id: Optional[str] = None,
    ) -> Optional[SensitiveWordPolicy]:
        with get_sync_db_session() as session:
            return session.exec(cls._scope_stmt(tenant_id, business_type, scope_type, scope_id)).first()

    @classmethod
    async def aget_policy(
        cls,
        tenant_id: int,
        business_type: str,
        scope_type: str = 'tenant',
        scope_id: Optional[str] = None,
    ) -> Optional[SensitiveWordPolicy]:
        async with get_async_db_session() as session:
            result = await session.exec(cls._scope_stmt(tenant_id, business_type, scope_type, scope_id))
            return result.first()

    @classmethod
    async def aupsert_policy(
        cls,
        tenant_id: int,
        business_type: str,
        *,
        enabled: bool,
        words_types: List[str],
        custom_words: str,
        auto_reply: str,
        extra_config: Dict[str, Any],
        operator_id: int,
        scope_type: str = 'tenant',
        scope_id: Optional[str] = None,
    ) -> SensitiveWordPolicy:
        final_scope_id = scope_id or str(tenant_id)
        async with get_async_db_session() as session:
            result = await session.exec(
                cls._scope_stmt(tenant_id, business_type, scope_type, final_scope_id)
            )
            policy = result.first()
            created = False
            if policy is None:
                policy = SensitiveWordPolicy(
                    tenant_id=tenant_id,
                    business_type=business_type,
                    scope_type=scope_type,
                    scope_id=final_scope_id,
                    created_by=operator_id,
                )
                created = True

            def apply_policy_values(target: SensitiveWordPolicy) -> None:
                target.enabled = enabled
                target.words_types = words_types
                target.custom_words = custom_words
                target.auto_reply = auto_reply
                target.extra_config = extra_config
                target.updated_by = operator_id

            apply_policy_values(policy)
            session.add(policy)
            try:
                await session.commit()
            except IntegrityError:
                if not created:
                    raise
                await session.rollback()
                result = await session.exec(
                    cls._scope_stmt(tenant_id, business_type, scope_type, final_scope_id)
                )
                policy = result.first()
                if policy is None:
                    raise
                apply_policy_values(policy)
                session.add(policy)
                await session.commit()
            await session.refresh(policy)
            return policy
