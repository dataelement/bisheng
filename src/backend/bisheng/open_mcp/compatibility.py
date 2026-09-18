"""Explicit one-way mapping from frozen Open API business results to MCP DTOs."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from bisheng.open_mcp.contracts import (
    FileItem,
    FileListData,
    FileRecord,
    KnowledgeResource,
    ResourceListData,
    RetrieveData,
)


def _object_data(value: Any) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    fields = getattr(value, "__dict__", None)
    if isinstance(fields, dict):
        return {key: item for key, item in fields.items() if not key.startswith("_")}
    raise TypeError(f"Unsupported business result type: {type(value).__name__}")


def _explicit_fields(model: type[BaseModel], value: Any) -> dict[str, Any]:
    source = _object_data(value)
    allowed = {field.alias or name for name, field in model.model_fields.items()}
    return {key: item for key, item in source.items() if key in allowed}


def map_knowledge_resource_to_mcp(value: Any) -> KnowledgeResource:
    return KnowledgeResource.model_validate(_explicit_fields(KnowledgeResource, value))


def map_resource_list_to_mcp(value: Any) -> ResourceListData:
    source = _object_data(value)
    return ResourceListData(
        data=[map_knowledge_resource_to_mcp(item) for item in source.get("data", [])],
        page_size=int(source.get("page_size", 0)),
        has_more=bool(source.get("has_more", False)),
        next_cursor=source.get("next_cursor"),
    )


def map_retrieve_to_mcp(value: Any) -> RetrieveData:
    return RetrieveData.model_validate(_explicit_fields(RetrieveData, value))


def map_file_record_to_mcp(value: Any) -> FileRecord:
    return FileRecord.model_validate(_explicit_fields(FileRecord, value))


def map_file_item_to_mcp(value: Any) -> FileItem:
    return FileItem.model_validate(_explicit_fields(FileItem, value))


def map_file_list_to_mcp(value: Any) -> FileListData:
    source = _object_data(value)
    return FileListData(
        data=[map_file_item_to_mcp(item) for item in source.get("data", [])],
        page_size=int(source.get("page_size", 0)),
        has_more=bool(source.get("has_more", False)),
        next_cursor=source.get("next_cursor"),
        writeable=bool(source.get("writeable", False)),
    )


__all__ = [
    "map_file_item_to_mcp",
    "map_file_list_to_mcp",
    "map_file_record_to_mcp",
    "map_knowledge_resource_to_mcp",
    "map_resource_list_to_mcp",
    "map_retrieve_to_mcp",
]
