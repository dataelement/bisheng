from bisheng.open_mcp.registry import TOOL_DEFINITIONS

FORBIDDEN_ARGUMENTS = {"authorization", "user_id", "tenant_id", "on_behalf_of", "file_path"}


def _properties_without_descriptions(node, path="$"):
    missing = []
    if isinstance(node, dict):
        for name, schema in node.get("properties", {}).items():
            property_path = f"{path}.{name}"
            if not schema.get("description"):
                missing.append(property_path)
            missing.extend(_properties_without_descriptions(schema, property_path))
        for key, value in node.items():
            if key != "properties":
                missing.extend(_properties_without_descriptions(value, f"{path}.{key}"))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            missing.extend(_properties_without_descriptions(value, f"{path}[{index}]"))
    return missing


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


def test_every_output_field_explains_its_business_meaning():
    for definition in TOOL_DEFINITIONS:
        schema = definition.to_mcp_tool().outputSchema
        assert not _properties_without_descriptions(schema), definition.name


def test_knowledge_space_only_fields_explain_applicability():
    tools = {definition.name: definition.to_mcp_tool() for definition in TOOL_DEFINITIONS}
    create_tool = tools["bisheng_knowledge_create"]

    input_description = create_tool.inputSchema["properties"]["is_released"]["description"]
    output_description = create_tool.outputSchema["properties"]["is_released"]["description"]

    assert "知识广场" in input_description
    assert "type=3" in input_description
    assert "知识广场" in output_description
    assert "type=0/1" in output_description


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
