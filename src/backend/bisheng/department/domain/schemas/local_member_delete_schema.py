"""DTOs for local organization member delete with asset transfer."""

from __future__ import annotations

from pydantic import BaseModel, Field


class LocalMemberDeleteReceiverPreview(BaseModel):
    user_id: int
    user_name: str
    source: str = Field(description="department_admin | platform_admin")
    department_id: int | None = None
    department_name: str | None = None


class LocalMemberDeletePreviewResponse(BaseModel):
    has_assets: bool
    counts: dict[str, int] = Field(default_factory=dict)
    transfer_count: int = 0
    linsight_delete_count: int = 0
    proposed_receiver: LocalMemberDeleteReceiverPreview | None = None


class LocalMemberDeleteTransferSummary(BaseModel):
    performed: bool = False
    receiver: LocalMemberDeleteReceiverPreview | None = None
    transferred_count: int = 0
    counts_by_type: dict[str, int] = Field(default_factory=dict)
    transfer_log_ids: list[str] = Field(default_factory=list)


class LocalMemberDeleteLinsightSummary(BaseModel):
    performed: bool = False
    deleted_count: int = 0
    counts: dict[str, int] = Field(default_factory=dict)


class LocalMemberDeletePersonalRecycleSummary(BaseModel):
    performed: bool = False
    recycled_count: int = 0
    folder_name: str = ""
    recycle_batch_id: str | None = None


class LocalMemberDeleteExecuteResponse(BaseModel):
    deleted_user_id: int
    transfer: LocalMemberDeleteTransferSummary
    linsight_deleted: LocalMemberDeleteLinsightSummary
    personal_recycled: LocalMemberDeletePersonalRecycleSummary = Field(
        default_factory=LocalMemberDeletePersonalRecycleSummary,
    )
