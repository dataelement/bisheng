from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Integer, String, UniqueConstraint, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT


class KnowledgeSpaceFileChangePolicyScope:
    ALL_SPACES = "all_spaces"
    PER_SPACE = "per_space"


class KnowledgeSpaceFileChangePolicyBase(SQLModelSerializable):
    tenant_id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, nullable=False, server_default=text("1")),
    )
    enabled: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default=text("1")),
    )
    scope: str = Field(
        default=KnowledgeSpaceFileChangePolicyScope.PER_SPACE,
        sa_column=Column(
            String(32),
            nullable=False,
            server_default=text("'per_space'"),
        ),
    )
    create_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT),
    )


class KnowledgeSpaceFileChangePolicy(KnowledgeSpaceFileChangePolicyBase, table=True):
    __tablename__ = "knowledge_space_file_change_policy"
    __table_args__ = (UniqueConstraint("tenant_id", name="uq_ks_file_change_policy_tenant"),)

    id: int | None = Field(
        default=None,
        sa_column=Column(
            BigInteger().with_variant(Integer, "sqlite"),
            primary_key=True,
            autoincrement=True,
        ),
    )


class KnowledgeSpaceFileChangeSettingBase(SQLModelSerializable):
    tenant_id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, nullable=False, server_default=text("1")),
    )
    space_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    approval_required: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default=text("1")),
    )
    create_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT),
    )


class KnowledgeSpaceFileChangeSetting(KnowledgeSpaceFileChangeSettingBase, table=True):
    __tablename__ = "knowledge_space_file_change_setting"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "space_id",
            name="uq_ks_file_change_setting_space",
        ),
    )

    id: int | None = Field(
        default=None,
        sa_column=Column(
            BigInteger().with_variant(Integer, "sqlite"),
            primary_key=True,
            autoincrement=True,
        ),
    )
