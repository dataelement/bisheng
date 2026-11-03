"""Upload-confirmation batch used only for post-parse similarity repair."""

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable


class KnowledgeUploadBatch(SQLModelSerializable, table=True):
    __tablename__ = "knowledge_upload_batch"
    __table_args__ = (UniqueConstraint("tenant_id", "batch_key", name="uk_upload_batch_tenant_key"),)

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: int = Field(sa_column=Column(Integer, nullable=False, index=True, comment="租户编号"))
    knowledge_id: int = Field(sa_column=Column(Integer, nullable=False, index=True, comment="知识库编号"))
    batch_key: str = Field(sa_column=Column(String(36), nullable=False, comment="一次确认上传的批次键"))
    created_by: int = Field(sa_column=Column(Integer, nullable=False, comment="创建该批次的用户编号"))
    revision: int = Field(
        default=0,
        sa_column=Column(
            Integer, nullable=False, server_default="0", comment="每有一个批次文件解析成功并进入相似收尾就加 1"
        ),
    )
    create_time: datetime | None = Field(
        default_factory=datetime.now,
        sa_column=Column(DateTime, nullable=False, comment="创建时间"),
    )
    update_time: datetime | None = Field(
        default_factory=datetime.now,
        sa_column=Column(DateTime, nullable=False, comment="更新时间"),
    )


class KnowledgeUploadBatchFile(SQLModelSerializable, table=True):
    __tablename__ = "knowledge_upload_batch_file"
    __table_args__ = (UniqueConstraint("file_id", name="uk_upload_batch_file"),)

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: int = Field(sa_column=Column(Integer, nullable=False, index=True, comment="租户编号"))
    batch_id: int = Field(sa_column=Column(Integer, nullable=False, index=True, comment="上传批次编号"))
    file_id: int = Field(sa_column=Column(Integer, nullable=False, comment="知识库文件编号"))
    create_time: datetime | None = Field(
        default_factory=datetime.now,
        sa_column=Column(DateTime, nullable=False, comment="加入批次的时间"),
    )
