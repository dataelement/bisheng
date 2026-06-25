from pydantic import BaseModel
from bisheng.database.models.review_tags import ApproveOrRejectEnum, TagResourceTypeEnum

class ApproveOrRejectRequest(BaseModel):
    tag_name: str
    status: ApproveOrRejectEnum
    reject_reason: str = None
    resource_type: TagResourceTypeEnum
