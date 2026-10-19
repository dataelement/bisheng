"""F086: which workflows reference which workflow as a subflow.

One row per (parent, child) pair found in the parent's current version.
Rows are rebuilt by ``SubflowService.sync_refs`` at every write entry of
``Flow.data``; the table is only read to block deletion and to warn on save.
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT


class WorkflowSubflowRefBase(SQLModelSerializable):
    tenant_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, nullable=False, server_default=text("1"), index=True, comment="Tenant ID"),
    )
    parent_flow_id: str = Field(
        sa_column=Column(String(64), nullable=False, index=True, comment="Workflow that contains the subflow node"),
    )
    child_flow_id: str = Field(
        sa_column=Column(String(64), nullable=False, index=True, comment="Workflow used as the subflow"),
    )
    create_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT),
    )


class WorkflowSubflowRef(WorkflowSubflowRefBase, table=True):
    __tablename__ = "workflow_subflow_ref"
    __table_args__ = (UniqueConstraint("parent_flow_id", "child_flow_id", name="uk_wsr_parent_child"),)

    id: int | None = Field(default=None, primary_key=True)
