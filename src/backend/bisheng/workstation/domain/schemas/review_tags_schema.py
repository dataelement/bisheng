from dataclasses import dataclass

from pydantic import BaseModel

from bisheng.database.models.review_tags import ApproveOrRejectEnum, TagResourceTypeEnum


@dataclass(frozen=True)
class ReviewTagSubmitterTarget:
    user_id: int
    knowledge_space_id: int | None = None
    file_id: int | None = None
    file_name: str | None = None
    file_type: str | None = None


class ApproveOrRejectRequest(BaseModel):
    tag_name: str
    status: ApproveOrRejectEnum
    reject_reason: str = None
    resource_type: TagResourceTypeEnum
    tag_library_id: int | None = None
    knowledge_id: int | None = None
