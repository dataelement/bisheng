from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

RUNTIME_STATE_NODE_ID = "__runtime__"
RUNTIME_USER_SELECTED_KNOWLEDGE_KEY = "user_selected_knowledge"
RUNTIME_KNOWLEDGE_SELECTION_FIELD = "__runtime_knowledge_selection"
MAX_RUNTIME_KNOWLEDGE_FILES = 20

RuntimeKnowledgeSourceType = Literal["knowledge", "space"]
RuntimeKnowledgeMode = Literal["source", "items"]
RuntimeKnowledgeRefType = Literal["file", "folder"]


def _parse_positive_int(value: Any, field_name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be an integer")
    if parsed <= 0:
        raise ValueError(f"{field_name} must be greater than 0")
    return parsed


class RuntimeKnowledgeSource(BaseModel):
    source_type: RuntimeKnowledgeSourceType
    source_id: int
    source_name: str = ""

    @field_validator("source_id", mode="before")
    @classmethod
    def parse_source_id(cls, value: Any) -> int:
        return _parse_positive_int(value, "knowledge source_id")


class RuntimeKnowledgeRef(BaseModel):
    id: int
    name: str = ""

    @field_validator("id", mode="before")
    @classmethod
    def parse_id(cls, value: Any) -> int:
        return _parse_positive_int(value, "knowledge scope id")


class RuntimeKnowledgeItem(RuntimeKnowledgeSource):
    ref_type: RuntimeKnowledgeRefType
    id: int
    name: str = ""

    @field_validator("id", mode="before")
    @classmethod
    def parse_id(cls, value: Any) -> int:
        return _parse_positive_int(value, "knowledge scope id")


class RuntimeKnowledgeSelection(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    mode: RuntimeKnowledgeMode
    whole_source: RuntimeKnowledgeSource | None = None
    items: list[RuntimeKnowledgeItem] = Field(default_factory=list)
    effective_file_count: int | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_shape(cls, value: Any) -> Any:
        if not isinstance(value, dict) or "mode" in value:
            return value

        source_type = value.get("source_type") or value.get("type")
        source_id = value.get("source_id")
        source_name = value.get("source_name") or ""
        files = value.get("files") or []
        folders = value.get("folders") or []
        if files or folders:
            items = []
            for one in files:
                items.append(
                    {
                        "source_type": source_type,
                        "source_id": source_id,
                        "source_name": source_name,
                        "ref_type": "file",
                        "id": one.get("id") if isinstance(one, dict) else getattr(one, "id", None),
                        "name": one.get("name", "") if isinstance(one, dict) else getattr(one, "name", ""),
                    }
                )
            for one in folders:
                items.append(
                    {
                        "source_type": source_type,
                        "source_id": source_id,
                        "source_name": source_name,
                        "ref_type": "folder",
                        "id": one.get("id") if isinstance(one, dict) else getattr(one, "id", None),
                        "name": one.get("name", "") if isinstance(one, dict) else getattr(one, "name", ""),
                    }
                )
            return {
                "mode": "items",
                "whole_source": None,
                "items": items,
                "effective_file_count": value.get("effective_file_count"),
            }

        return {
            "mode": "source",
            "whole_source": {
                "source_type": source_type,
                "source_id": source_id,
                "source_name": source_name,
            },
            "items": [],
            "effective_file_count": value.get("effective_file_count"),
        }

    @field_validator("effective_file_count", mode="before")
    @classmethod
    def parse_effective_file_count(cls, value: Any) -> int | None:
        if value in (None, ""):
            return None
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            raise ValueError("effective_file_count must be an integer")
        if parsed < 0:
            raise ValueError("effective_file_count must be greater than or equal to 0")
        return parsed

    @model_validator(mode="after")
    def validate_scope(self) -> "RuntimeKnowledgeSelection":
        if self.mode == "source":
            if self.whole_source is None:
                raise ValueError("请选择知识库或知识空间。")
            if self.items:
                raise ValueError("完整知识来源不能与文件或文件夹范围同时选择。")
            return self

        if self.whole_source is not None:
            raise ValueError("文件或文件夹范围不能与完整知识来源同时选择。")
        if not self.items:
            raise ValueError("请选择知识库或知识空间。")
        if len({item.source_type for item in self.items}) > 1:
            raise ValueError("文件或文件夹范围不能同时选择知识库和知识空间。")
        if (self.effective_file_count or 0) > MAX_RUNTIME_KNOWLEDGE_FILES:
            raise ValueError(f"一次最多可选择{MAX_RUNTIME_KNOWLEDGE_FILES}个文件。")
        return self

    def has_file_or_folder_scope(self) -> bool:
        return self.mode == "items" and bool(self.items)

    def file_ids(self) -> list[int]:
        return [item.id for item in self.items if item.ref_type == "file"]

    def folder_ids(self) -> list[int]:
        return [item.id for item in self.items if item.ref_type == "folder"]

    def item_groups(self, source_type: RuntimeKnowledgeSourceType) -> dict[int, list[RuntimeKnowledgeItem]]:
        grouped: dict[int, list[RuntimeKnowledgeItem]] = {}
        for item in self.items:
            if item.source_type != source_type:
                continue
            grouped.setdefault(item.source_id, []).append(item)
        return grouped

    def source_ids(self, source_type: RuntimeKnowledgeSourceType) -> list[int]:
        if self.mode == "source":
            if self.whole_source and self.whole_source.source_type == source_type:
                return [self.whole_source.source_id]
            return []
        return sorted(self.item_groups(source_type).keys())


def parse_runtime_knowledge_selection(value: Any) -> RuntimeKnowledgeSelection:
    if value is None:
        raise ValueError("请选择知识库或知识空间。")
    if isinstance(value, RuntimeKnowledgeSelection):
        return value
    if not isinstance(value, dict):
        raise ValueError("自选知识范围参数格式错误。")
    return RuntimeKnowledgeSelection.model_validate(value)
