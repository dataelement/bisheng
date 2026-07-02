from pydantic import BaseModel

from bisheng.database.models.review_tags import ApproveOrRejectEnum, TagResourceTypeEnum


class ApproveOrRejectRequest(BaseModel):
    tag_name: str
    status: ApproveOrRejectEnum
    reject_reason: str = None
    resource_type: TagResourceTypeEnum
    tag_library_id: int | None = None
    knowledge_id: int | None = None
