from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class ApprovalDecisionActionEnum(str, Enum):
    APPROVE = 'approve'
    REJECT = 'reject'


class DepartmentKnowledgeSpaceApprovalSettings(BaseModel):
    approval_enabled: bool = Field(default=True)
    sensitive_check_enabled: bool = Field(default=False)


class ApprovalRequestDecisionReq(BaseModel):
    action: ApprovalDecisionActionEnum
    reason: Optional[str] = Field(default=None, max_length=2000)


class ApprovalRequestResp(BaseModel):
    id: int
    request_type: str
    status: str
    review_mode: str
    space_id: int
    department_id: int
    parent_folder_id: Optional[int] = None
    applicant_user_id: int
    applicant_user_name: str
    reviewer_user_ids: List[int] = Field(default_factory=list)
    file_count: int
    payload_json: Dict
    safety_status: str
    safety_reason: Optional[str] = None
    decision_reason: Optional[str] = None
    decided_by: Optional[int] = None
    message_id: Optional[int] = None
    create_time: Optional[str] = None
    update_time: Optional[str] = None


class ApprovalRequestListResp(BaseModel):
    data: List[ApprovalRequestResp] = Field(default_factory=list)
    total: int = 0
