"""知识库文档纠错单, 待处理占位和第一次通过的积分名额."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT

FILE_CORRECTION_SCENARIO = "knowledge_file_correction"
FILE_CORRECTION_SCENARIO_NAME = "文档纠错"
FILE_CORRECTION_CONTENT_LIMIT = 500

CORRECTION_PENDING = "pending"
CORRECTION_APPROVED = "approved"
CORRECTION_REJECTED = "rejected"
CORRECTION_WITHDRAWN = "withdrawn"
CORRECTION_CANCELLED = "cancelled"

AWARD_RESERVED = "reserved"
AWARD_AWARDED = "awarded"
AWARD_SKIPPED = "skipped"


class KnowledgeFileCorrection(SQLModelSerializable, table=True):
    """一篇文档上的一条纠错. 正文只放在这张表."""

    __tablename__ = "knowledge_file_correction"

    id: int | None = Field(
        default=None,
        sa_column=Column(Integer, primary_key=True, autoincrement=True, comment="主键"),
    )
    tenant_id: int = Field(
        default=1,
        sa_column=Column(Integer, nullable=False, server_default=text("1"), index=True, comment="租户ID"),
    )
    file_id: int = Field(sa_column=Column(Integer, nullable=False, index=True, comment="知识库文件ID"))
    knowledge_id: int = Field(sa_column=Column(Integer, nullable=False, index=True, comment="知识库ID"))
    applicant_user_id: int = Field(sa_column=Column(Integer, nullable=False, index=True, comment="反馈人用户ID"))
    applicant_user_name: str = Field(
        default="",
        sa_column=Column(String(255), nullable=False, server_default=text("''"), comment="反馈人姓名快照"),
    )
    uploader_user_id: int = Field(
        sa_column=Column(Integer, nullable=False, index=True, comment="提交时冻结的上传人用户ID")
    )
    uploader_user_name: str = Field(
        default="",
        sa_column=Column(String(255), nullable=False, server_default=text("''"), comment="上传人姓名快照"),
    )
    file_name: str = Field(
        default="",
        sa_column=Column(String(255), nullable=False, server_default=text("''"), comment="文档名快照"),
    )
    content: str = Field(sa_column=Column(String(500), nullable=False, comment="纠错说明, 最多500字"))
    original_error: str | None = Field(
        default=None,
        sa_column=Column(String(500), nullable=True, comment="用户认为原文中错误的地方, 最多500字"),
    )
    corrected_content: str | None = Field(
        default=None,
        sa_column=Column(String(500), nullable=True, comment="用户纠正后的内容, 最多500字"),
    )
    status: str = Field(
        default=CORRECTION_PENDING,
        sa_column=Column(
            String(16), nullable=False, index=True, comment="状态: pending/approved/rejected/withdrawn/cancelled"
        ),
    )
    approval_instance_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, nullable=True, index=True, comment="审批实例ID"),
    )
    pending_update_file_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, nullable=True, comment="采纳并更新已登记、尚未替换完成的新文件ID"),
    )
    create_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"), comment="创建时间"),
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT, comment="更新时间"),
    )


class KnowledgeFileCorrectionOpen(SQLModelSerializable, table=True):
    """同一租户, 同一文档, 同一反馈人只能有一条待处理纠错."""

    __tablename__ = "knowledge_file_correction_open"

    tenant_id: int = Field(
        sa_column=Column(Integer, primary_key=True, nullable=False, comment="租户ID"),
    )
    file_id: int = Field(sa_column=Column(Integer, primary_key=True, nullable=False, comment="知识库文件ID"))
    applicant_user_id: int = Field(
        sa_column=Column(Integer, primary_key=True, nullable=False, comment="反馈人用户ID"),
    )
    correction_id: int = Field(sa_column=Column(Integer, nullable=False, comment="待处理纠错单ID"))


class KnowledgeFileCorrectionAward(SQLModelSerializable, table=True):
    """一条纠错的发分结果. 采纳并更新按条发放, 不按人按文档合并成一行."""

    __tablename__ = "knowledge_file_correction_award"

    id: int | None = Field(
        default=None,
        sa_column=Column(Integer, primary_key=True, autoincrement=True, comment="主键"),
    )
    tenant_id: int = Field(
        default=1,
        sa_column=Column(Integer, nullable=False, server_default=text("1"), index=True, comment="租户ID"),
    )
    file_id: int = Field(sa_column=Column(Integer, nullable=False, index=True, comment="被纠错的知识库文件ID"))
    applicant_user_id: int = Field(sa_column=Column(Integer, nullable=False, index=True, comment="反馈人用户ID"))
    correction_id: int = Field(
        sa_column=Column(Integer, nullable=False, unique=True, comment="纠错单ID, 一条纠错只发一次")
    )
    award_kind: str = Field(sa_column=Column(String(16), nullable=False, comment="发分类型: adopt/update"))
    award_state: str = Field(
        default=AWARD_RESERVED,
        sa_column=Column(String(16), nullable=False, comment="名额结果: reserved/awarded/skipped"),
    )
    create_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"), comment="创建时间"),
    )
