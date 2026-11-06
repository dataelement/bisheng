from bisheng.open_mcp.registry import TOOL_DEFINITIONS

FORBIDDEN_ARGUMENTS = {"authorization", "user_id", "tenant_id", "on_behalf_of", "file_path"}


def test_every_tool_exposes_object_schemas_and_annotations():
    for definition in TOOL_DEFINITIONS:
        tool = definition.to_mcp_tool()
        assert tool.inputSchema["type"] == "object"
        assert tool.outputSchema["type"] == "object"
        assert tool.inputSchema.get("additionalProperties") is False
        assert tool.outputSchema.get("additionalProperties") is False
        assert FORBIDDEN_ARGUMENTS.isdisjoint(tool.inputSchema.get("properties", {}))
        assert tool.annotations is not None
        assert tool.annotations.openWorldHint is not None


def test_batch_delete_and_upload_are_mcp_object_adaptations():
    tools = {definition.name: definition.to_mcp_tool() for definition in TOOL_DEFINITIONS}
    batch = tools["bisheng_knowledge_files_delete"].inputSchema
    assert batch["required"] == ["file_ids"]
    assert batch["properties"]["file_ids"]["type"] == "array"

    upload = tools["bisheng_knowledge_file_upload"].inputSchema
    assert {"content_base64", "file_url"} <= upload["properties"].keys()
    assert "file_path" not in upload["properties"]
    assert "callback_url" not in upload["properties"]


def test_outputs_keep_actions_and_structured_tags_without_permission_ids():
    tools = {definition.name: definition.to_mcp_tool() for definition in TOOL_DEFINITIONS}
    resource_schema = tools["bisheng_knowledge_create"].outputSchema
    assert "actions" in resource_schema["properties"]
    assert "permission_ids" not in resource_schema["properties"]

    file_schema = tools["bisheng_knowledge_file_list"].outputSchema
    serialized = str(file_schema)
    assert "TagItem" in serialized
    assert "permission_ids" not in serialized
