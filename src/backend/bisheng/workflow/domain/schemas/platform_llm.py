"""昆联平台大模型节点的契约模型与参数校验。"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

NODE_TYPE = "platform_llm"


class PlatformLLMContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=False)


class PlatformModelReference(BaseModel):
    """工作流节点保存的固定模型版本引用，不得替换为 latest。"""

    model_config = ConfigDict(extra="allow")

    resource_id: str = Field(min_length=1, max_length=256)
    version_id: str = Field(min_length=1, max_length=256)
    call_id: str = Field(min_length=1, max_length=256)
    name: str = ""
    version: str = ""

    @field_validator("version_id", "call_id")
    @classmethod
    def forbid_latest(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned or cleaned.lower() == "latest":
            raise ValueError("必须使用固定模型版本标识，不得使用 latest")
        return cleaned


class PlatformModelSummary(BaseModel):
    """模型列表接口返回的单条模型摘要。"""

    model_config = ConfigDict(extra="allow")

    resource_type: str = "model"
    resource_id: str = Field(min_length=1)
    version_id: str = Field(min_length=1)
    name: str = ""
    description: str = ""
    version: str = ""
    status: str = "published"
    allowed_actions: list[str] = Field(default_factory=list)
    call_id: str = Field(min_length=1)
    input_schema: Any = None
    output_schema: Any = None


class PlatformModelListPage(BaseModel):
    """模型列表分页结果。"""

    items: list[PlatformModelSummary]
    page_size: int
    has_more: bool
    next_cursor: str | None = None


class PlatformLLMNodeConfig(BaseModel):
    """PlatformLLMNode 节点核心配置。"""

    model_ref: PlatformModelReference
    temperature: float = Field(default=1.0, ge=0.0, le=2.0)
    system_prompt: str = ""
    user_prompt: str = Field(min_length=1)
    output_user: bool = True


def extract_node_params(node_data: dict[str, Any]) -> dict[str, Any]:
    """从工作流节点 group_params 中提取扁平参数字典。"""
    params: dict[str, Any] = {}
    for group in node_data.get("group_params") or []:
        for param in group.get("params") or []:
            key = param.get("key")
            if isinstance(key, str) and key:
                params[key] = param.get("value")
    return params


def validate_node_config(node_data: dict[str, Any]) -> PlatformLLMNodeConfig:
    """校验昆联平台大模型节点的必填配置。"""
    params = extract_node_params(node_data)
    return PlatformLLMNodeConfig(
        model_ref=params.get("model_ref"),
        temperature=1.0 if params.get("temperature") is None else params.get("temperature"),
        system_prompt=params.get("system_prompt") or "",
        user_prompt=params.get("user_prompt") or "",
        output_user=True if params.get("output_user") is None else bool(params.get("output_user")),
    )
