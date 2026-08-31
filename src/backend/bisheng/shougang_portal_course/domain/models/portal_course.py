from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CHAR,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT, LargeText


def _uuid_hex() -> str:
    return uuid.uuid4().hex


class PortalCourseCatalog(SQLModelSerializable, table=True):
    """Multi-level course catalog. Fields follow YunXueTang kngCatalog."""

    __tablename__ = "portal_course_catalog"
    __table_args__ = (
        Index(
            "ix_portal_catalog_tenant_parent_order",
            "tenant_id",
            "parent_id",
            "order_index",
        ),
        Index(
            "ix_portal_catalog_tenant_deleted_opened",
            "tenant_id",
            "deleted",
            "opened",
        ),
        Index("ix_portal_catalog_tenant_routing", "tenant_id", "routing_path"),
        {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    id: str = Field(
        default_factory=_uuid_hex,
        sa_column=Column(CHAR(32), primary_key=True, nullable=False),
    )
    tenant_id: int = Field(sa_column=Column(Integer, nullable=False))
    name: str = Field(sa_column=Column(String(200), nullable=False))
    description: str = Field(
        default="",
        sa_column=Column(String(200), nullable=False, server_default=text("''")),
    )
    parent_id: str | None = Field(
        default=None,
        sa_column=Column(CHAR(32), ForeignKey("portal_course_catalog.id"), nullable=True),
    )
    routing_path: str = Field(sa_column=Column(String(100), nullable=False))
    catalog_id_path: str = Field(sa_column=Column(String(1000), nullable=False))
    catalog_name_path: str = Field(sa_column=Column(String(1000), nullable=False))
    order_index: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default=text("0")),
    )
    deleted: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=text("0")),
    )
    opened: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default=text("1")),
    )
    create_user: int = Field(sa_column=Column(Integer, nullable=False))
    update_user: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default=text("0")),
    )
    create_time: datetime = Field(
        default_factory=datetime.now,
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=text("CURRENT_TIMESTAMP"),
        ),
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=UPDATE_TIME_SERVER_DEFAULT,
        ),
    )


class PortalCourse(SQLModelSerializable, table=True):
    """Tenant-scoped course configured by portal administrators."""

    __tablename__ = "portal_course"
    __table_args__ = (
        Index(
            "ix_portal_course_tenant_enabled_home_order",
            "tenant_id",
            "enabled",
            "show_on_home",
            "sort_order",
        ),
        Index("ix_portal_course_tenant_order", "tenant_id", "sort_order"),
        Index("ix_portal_course_tenant_catalog", "tenant_id", "catalog_id"),
        UniqueConstraint(
            "tenant_id",
            "external_id",
            name="uk_portal_course_tenant_external_id",
        ),
        {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    id: str = Field(
        default_factory=_uuid_hex,
        sa_column=Column(CHAR(32), primary_key=True, nullable=False),
    )
    tenant_id: int = Field(sa_column=Column(Integer, nullable=False))
    catalog_id: str | None = Field(
        default=None,
        sa_column=Column(
            CHAR(32),
            ForeignKey("portal_course_catalog.id"),
            nullable=True,
        ),
    )
    course_type: str = Field(
        default="local",
        sa_column=Column(
            String(16),
            nullable=False,
            server_default=text("'local'"),
        ),
    )
    external_url: str = Field(
        default="",
        sa_column=Column(
            String(2048),
            nullable=False,
            server_default=text("''"),
        ),
    )
    external_id: str | None = Field(
        default=None,
        sa_column=Column(String(128), nullable=True),
    )
    cover_url: str = Field(
        default="",
        sa_column=Column(
            String(2048),
            nullable=False,
            server_default=text("''"),
        ),
    )
    source_updated_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=True),
    )
    name: str = Field(sa_column=Column(String(200), nullable=False))
    instructor: str = Field(
        default="",
        sa_column=Column(String(100), nullable=False, server_default=text("''")),
    )
    organization: str = Field(
        default="",
        sa_column=Column(String(200), nullable=False, server_default=text("''")),
    )
    description: str = Field(
        default="",
        sa_column=Column(Text, nullable=False),
    )
    tags_json: str = Field(
        default="[]",
        sa_column=Column(LargeText, nullable=False),
    )
    enabled: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=text("0")),
    )
    show_on_home: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=text("0")),
    )
    sort_order: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default=text("0")),
    )
    create_user: int = Field(sa_column=Column(Integer, nullable=False))
    create_time: datetime = Field(
        default_factory=datetime.now,
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=text("CURRENT_TIMESTAMP"),
        ),
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=UPDATE_TIME_SERVER_DEFAULT,
        ),
    )


class PortalCourseVideo(SQLModelSerializable, table=True):
    """One playable item inside a course directory."""

    __tablename__ = "portal_course_video"
    __table_args__ = (
        Index(
            "ix_portal_video_tenant_course_enabled_order",
            "tenant_id",
            "course_id",
            "enabled",
            "sort_order",
        ),
        Index("ix_portal_video_tenant_object", "tenant_id", "object_name"),
        {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    id: str = Field(
        default_factory=_uuid_hex,
        sa_column=Column(CHAR(32), primary_key=True, nullable=False),
    )
    tenant_id: int = Field(sa_column=Column(Integer, nullable=False))
    course_id: str = Field(
        sa_column=Column(
            CHAR(32),
            ForeignKey("portal_course.id"),
            nullable=False,
        )
    )
    title: str = Field(sa_column=Column(String(200), nullable=False))
    source_type: str = Field(sa_column=Column(String(16), nullable=False))
    object_name: str | None = Field(
        default=None,
        sa_column=Column(String(512), nullable=True),
    )
    source_url: str | None = Field(
        default=None,
        sa_column=Column(String(2048), nullable=True),
    )
    original_filename: str | None = Field(
        default=None,
        sa_column=Column(String(255), nullable=True),
    )
    duration_seconds: int = Field(sa_column=Column(Integer, nullable=False))
    enabled: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=text("0")),
    )
    sort_order: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default=text("0")),
    )
    create_time: datetime = Field(
        default_factory=datetime.now,
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=text("CURRENT_TIMESTAMP"),
        ),
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=UPDATE_TIME_SERVER_DEFAULT,
        ),
    )


class PortalCourseVideoProgress(SQLModelSerializable, table=True):
    """The single mutable progress row for one tenant, user, and video."""

    __tablename__ = "portal_course_video_progress"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "user_id",
            "video_id",
            name="uk_portal_progress_tenant_user_video",
        ),
        Index("ix_portal_progress_tenant_video", "tenant_id", "video_id"),
        {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    id: str = Field(
        default_factory=_uuid_hex,
        sa_column=Column(CHAR(32), primary_key=True, nullable=False),
    )
    tenant_id: int = Field(sa_column=Column(Integer, nullable=False))
    user_id: int = Field(sa_column=Column(Integer, nullable=False))
    video_id: str = Field(
        sa_column=Column(
            CHAR(32),
            ForeignKey("portal_course_video.id"),
            nullable=False,
        )
    )
    progress_seconds: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default=text("0")),
    )
    completed: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=text("0")),
    )
    completed_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=True),
    )
    create_time: datetime = Field(
        default_factory=datetime.now,
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=text("CURRENT_TIMESTAMP"),
        ),
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=UPDATE_TIME_SERVER_DEFAULT,
        ),
    )


class PortalCourseMediaCleanup(SQLModelSerializable, table=True):
    """Durable cleanup work for uploaded course media objects."""

    __tablename__ = "portal_course_media_cleanup"
    __table_args__ = (
        Index("ix_portal_cleanup_status_not_before", "status", "not_before"),
        Index("ix_portal_cleanup_status_lease", "status", "lease_until"),
        Index(
            "ix_portal_cleanup_tenant_object_status",
            "tenant_id",
            "object_name",
            "status",
        ),
        {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    id: str = Field(
        default_factory=_uuid_hex,
        sa_column=Column(CHAR(32), primary_key=True, nullable=False),
    )
    tenant_id: int = Field(sa_column=Column(Integer, nullable=False))
    object_name: str = Field(sa_column=Column(String(512), nullable=False))
    reason: str = Field(sa_column=Column(String(32), nullable=False))
    status: str = Field(
        default="pending",
        sa_column=Column(
            String(16),
            nullable=False,
            server_default=text("'pending'"),
        ),
    )
    not_before: datetime = Field(sa_column=Column(DateTime, nullable=False))
    lease_until: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=True),
    )
    attempt_count: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default=text("0")),
    )
    last_error: str | None = Field(
        default=None,
        sa_column=Column(String(1000), nullable=True),
    )
    create_time: datetime = Field(
        default_factory=datetime.now,
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=text("CURRENT_TIMESTAMP"),
        ),
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=UPDATE_TIME_SERVER_DEFAULT,
        ),
    )
