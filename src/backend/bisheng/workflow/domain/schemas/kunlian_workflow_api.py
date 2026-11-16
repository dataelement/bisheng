"""窄管理请求DTO与旧服务的兼容结构, 不跨API导入schema。"""

from pydantic import BaseModel, ConfigDict


class WorkflowCreateData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    description: str | None = None
    data: dict | None = None
    logo: str | None = None
    flow_type: int = 10


class VersionData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    description: str | None = None
    data: dict | None = None
    original_version_id: int | None = None
    flow_type: int = 10


def workflow_create_dto(values):
    return WorkflowCreateData.model_validate(values)


def version_dto(values):
    return VersionData.model_validate(values)
