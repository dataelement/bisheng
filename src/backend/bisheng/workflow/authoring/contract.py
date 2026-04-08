from datetime import datetime
from enum import Enum
from typing import Optional, Any

from pydantic import BaseModel, Field


WORKFLOW_AUTHORING_SCHEMA_VERSION = 'workflow-authoring.v1'


class ValidationSeverity(str, Enum):
    ERROR = 'error'
    WARNING = 'warning'


class WorkflowTabOption(BaseModel):
    key: str = ''
    label: str = ''
    help: Optional[str] = None


class WorkflowTabDescriptor(BaseModel):
    value: Optional[str] = None
    options: list[WorkflowTabOption] = Field(default_factory=list)


class WorkflowParamMetadata(BaseModel):
    display_name: str = ''
    group_name: str = ''
    type: Optional[str] = None
    required: bool = False
    show: bool = True
    options: Optional[Any] = None
    scope: Optional[Any] = None
    placeholder: Optional[str] = None
    refresh: bool = False
    value: Optional[Any] = None


class WorkflowParamGroupDescriptor(BaseModel):
    name: str = ''
    group_key: Optional[str] = None
    param_keys: list[str] = Field(default_factory=list)


class WorkflowManifest(BaseModel):
    flow_id: str
    name: str = ''
    description: Optional[str] = None
    status: str = 'offline'
    current_version_id: Optional[int] = None
    editable_version_id: Optional[int] = None
    draft_revision: int = 0
    schema_version: str = WORKFLOW_AUTHORING_SCHEMA_VERSION


class WorkflowVersionSummary(BaseModel):
    version_id: int
    name: str = ''
    description: Optional[str] = None
    is_current: bool = False
    is_editable: bool = False
    is_external_draft: bool = False
    original_version_id: Optional[int] = None
    draft_revision: int = 0
    schema_version: str = WORKFLOW_AUTHORING_SCHEMA_VERSION
    create_time: Optional[datetime] = None
    update_time: Optional[datetime] = None


class WorkflowGraphNodeDescriptor(BaseModel):
    id: str
    type: str = ''
    name: str = ''
    description: Optional[str] = None
    tab: Optional[WorkflowTabDescriptor] = None
    param_keys: list[str] = Field(default_factory=list)
    params: dict[str, WorkflowParamMetadata] = Field(default_factory=dict)


class WorkflowGraphDescriptor(BaseModel):
    flow_id: str
    version_id: int
    draft_revision: int = 0
    schema_version: str = WORKFLOW_AUTHORING_SCHEMA_VERSION
    nodes: list[WorkflowGraphNodeDescriptor] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)


class NodeTypeDescriptor(BaseModel):
    type: str
    display_name: str = ''
    description: str = ''
    param_keys: list[str] = Field(default_factory=list)
    dynamic_template: bool = False
    schema_version: str = WORKFLOW_AUTHORING_SCHEMA_VERSION


class NodeTemplateDescriptor(BaseModel):
    node_type: str
    display_name: str = ''
    description: str = ''
    tab: Optional[WorkflowTabDescriptor] = None
    groups: list[WorkflowParamGroupDescriptor] = Field(default_factory=list)
    params: dict[str, WorkflowParamMetadata] = Field(default_factory=dict)
    dynamic_template: bool = False
    schema_version: str = WORKFLOW_AUTHORING_SCHEMA_VERSION


class ValidationDiagnostic(BaseModel):
    code: str = ''
    severity: ValidationSeverity = ValidationSeverity.ERROR
    message: str
    node_id: Optional[str] = None
    field_path: Optional[str] = None
    suggested_fix: Optional[str] = None
