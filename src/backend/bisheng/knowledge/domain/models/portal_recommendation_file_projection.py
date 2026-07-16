"""Rebuildable lightweight file projection used by portal recommendation."""

from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Index, Integer, SmallInteger, String, UniqueConstraint, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT


class PortalRecommendationFileProjection(SQLModelSerializable, table=True):
    __tablename__ = "portal_recommendation_file_projection"

    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )
    tenant_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            nullable=False,
            server_default=text("1"),
            comment="Tenant ID",
        ),
    )
    file_id: int = Field(sa_column=Column(Integer, nullable=False, comment="knowledgefile.id"))
    space_id: int = Field(sa_column=Column(Integer, nullable=False, comment="Owning knowledge space ID"))
    business_domain_code: str | None = Field(
        default=None,
        sa_column=Column(String(16), nullable=True, comment="Normalized business domain code"),
    )
    permission_scope: str = Field(
        default="unknown",
        sa_column=Column(
            String(16),
            nullable=False,
            server_default=text("'unknown'"),
            comment="inherited/custom/unknown",
        ),
    )
    recommendable: int = Field(
        default=0,
        sa_column=Column(
            SmallInteger,
            nullable=False,
            server_default=text("0"),
            comment="Whether the file may enter shared recommendation pools",
        ),
    )
    reason_code: str = Field(
        default="unknown",
        sa_column=Column(
            String(32),
            nullable=False,
            server_default=text("'unknown'"),
            comment="Projection eligibility reason",
        ),
    )
    source_update_time: datetime = Field(
        sa_column=Column(DateTime, nullable=False, comment="Source file update timestamp snapshot"),
    )
    projection_version: int = Field(
        default=0,
        sa_column=Column(
            BigInteger,
            nullable=False,
            server_default=text("0"),
            comment="Monotonic per-file projection version",
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

    __table_args__ = (
        UniqueConstraint("tenant_id", "file_id", name="uk_portal_rec_projection_file"),
        Index(
            "ix_prfp_domain_recency",
            "tenant_id",
            "business_domain_code",
            "recommendable",
            "source_update_time",
            "file_id",
        ),
        Index(
            "ix_prfp_generic_recency",
            "tenant_id",
            "recommendable",
            "source_update_time",
            "file_id",
        ),
        Index(
            "ix_prfp_space_recommendable",
            "tenant_id",
            "space_id",
            "recommendable",
        ),
    )
