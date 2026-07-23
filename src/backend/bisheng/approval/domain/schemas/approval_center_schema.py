from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class ApprovalGateDecision(str, Enum):
    PASS = 'pass'
    PENDING = 'pending'
    EXCEPTION = 'exception'


class ApprovalGateRequest(BaseModel):
    tenant_id: int
    scenario_code: str
    business_key: str
    business_resource_type: str
    business_resource_id: str
    business_name: str
    applicant_user_id: int
    applicant_user_name: str
    applicant_department_id: int | None = None
    reason: str | None = None
    payload_snapshot: dict[str, Any] = Field(default_factory=dict)
    detail_snapshot: dict[str, Any] = Field(default_factory=dict)
    ip_address: str | None = None
    duplicate_active_statuses: list[str] | None = None


class ApprovalGateResult(BaseModel):
    decision: ApprovalGateDecision
    instance_id: int
    task_ids: list[int] = Field(default_factory=list)
    exception_type: str | None = None


class ApprovalPresetValueOption(BaseModel):
    value: str
    label: str


class ApprovalPresetConditionField(BaseModel):
    field: str
    label: str
    type: str = 'text'
    values: list[ApprovalPresetValueOption] = Field(default_factory=list)
    selector_type: str | None = None


class ApprovalPresetApproverSource(BaseModel):
    source_type: str
    label: str


class ApprovalScenarioPreset(BaseModel):
    scenario_code: str
    scenario_name: str
    handler_key: str
    condition_fields: list[str] = Field(default_factory=list)
    approver_source_types: list[str] = Field(default_factory=list)
    condition_field_options: list[ApprovalPresetConditionField] = Field(default_factory=list)
    approver_source_options: list[ApprovalPresetApproverSource] = Field(default_factory=list)


class DepartmentFileViewApplyRequest(BaseModel):
    space_id: int
    file_id: int
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, value):
        return str(value or "").strip()


class DepartmentFileViewAccessResponse(BaseModel):
    space_id: int
    file_id: int
    status: str
    content_access: str
    access_source: str | None = None
    can_download: bool = False
    instance_id: int | None = None
    latest_instance_status: str | None = None
    safe_metadata: dict[str, Any] = Field(default_factory=dict)
