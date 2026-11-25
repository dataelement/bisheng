"""Knowledge and file metadata MCP tool handlers."""

from __future__ import annotations

from bisheng.open_mcp import metadata
from bisheng.open_mcp.compatibility import map_file_metadata_list_to_mcp, map_metadata_fields_to_mcp
from bisheng.open_mcp.contracts import (
    FileMetadataDeleteInput,
    FileMetadataListInput,
    FileMetadataWriteInput,
    MetadataFieldsAddInput,
    MetadataFieldsDeleteInput,
    MetadataFieldsGetInput,
    MetadataFieldsRenameInput,
    OperationResult,
)


async def metadata_fields_add(arguments: MetadataFieldsAddInput):
    await metadata.add_fields(
        knowledge_id=arguments.knowledge_id,
        fields=[item.model_dump() for item in arguments.metadata_fields],
    )
    return OperationResult()


async def metadata_fields_rename(arguments: MetadataFieldsRenameInput):
    await metadata.rename_fields(
        knowledge_id=arguments.knowledge_id,
        fields=[item.model_dump() for item in arguments.metadata_fields],
    )
    return OperationResult()


async def metadata_fields_delete(arguments: MetadataFieldsDeleteInput):
    await metadata.delete_fields(knowledge_id=arguments.knowledge_id, field_names=arguments.field_names)
    return OperationResult()


async def metadata_fields_get(arguments: MetadataFieldsGetInput):
    return map_metadata_fields_to_mcp(await metadata.list_fields(knowledge_id=arguments.knowledge_id))


async def file_metadata_add(arguments: FileMetadataWriteInput):
    await metadata.add_file_metadata(
        knowledge_id=arguments.knowledge_id,
        items=[item.model_dump() for item in arguments.items],
    )
    return OperationResult()


async def file_metadata_modify(arguments: FileMetadataWriteInput):
    await metadata.modify_file_metadata(
        knowledge_id=arguments.knowledge_id,
        items=[item.model_dump() for item in arguments.items],
    )
    return OperationResult()


async def file_metadata_delete(arguments: FileMetadataDeleteInput):
    await metadata.delete_file_metadata(
        knowledge_id=arguments.knowledge_id,
        items=[item.model_dump() for item in arguments.items],
    )
    return OperationResult()


async def file_metadata_list(arguments: FileMetadataListInput):
    return map_file_metadata_list_to_mcp(
        await metadata.list_file_metadata(
            knowledge_id=arguments.knowledge_id,
            knowledge_file_ids=arguments.knowledge_file_ids,
        )
    )


METADATA_HANDLERS = {
    "bisheng_knowledge_metadata_fields_add": metadata_fields_add,
    "bisheng_knowledge_metadata_fields_rename": metadata_fields_rename,
    "bisheng_knowledge_metadata_fields_delete": metadata_fields_delete,
    "bisheng_knowledge_metadata_fields_get": metadata_fields_get,
    "bisheng_knowledge_file_metadata_add": file_metadata_add,
    "bisheng_knowledge_file_metadata_modify": file_metadata_modify,
    "bisheng_knowledge_file_metadata_delete": file_metadata_delete,
    "bisheng_knowledge_file_metadata_list": file_metadata_list,
}


__all__ = ["METADATA_HANDLERS"]
