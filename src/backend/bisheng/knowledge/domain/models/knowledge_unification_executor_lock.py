"""F118 global control row; never held by a business batch connection."""

from datetime import datetime

from sqlalchemy import CheckConstraint, Column, Integer, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.knowledge.domain.models.knowledge_unification_run import unification_now


class KnowledgeUnificationExecutorLock(SQLModelSerializable, table=True):
    __tablename__ = "knowledge_unification_executor_lock"
    __table_args__ = (CheckConstraint("tenant_id = 1", name="ck_kun_executor_root"),)

    id: str = Field(default="f118-global", primary_key=True, max_length=32)
    tenant_id: int | None = Field(
        default=1, sa_column=Column(Integer, nullable=False, server_default=text("1"), index=True)
    )
    create_time: datetime = Field(default_factory=unification_now)
    update_time: datetime = Field(default_factory=unification_now)
