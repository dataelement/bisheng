from bisheng.open_api.domain.context import OpenApiPrincipal
from bisheng.open_mcp.registry import SOURCE_ALLOWLIST, TOOL_DEFINITIONS, TOOL_REGISTRY, list_tools_for

EXPECTED_SOURCES = {
    ("GET", "/api/v2/filelib/"),
    ("POST", "/api/v2/filelib/"),
    ("PUT", "/api/v2/filelib/"),
    ("DELETE", "/api/v2/filelib/{knowledge_id}"),
    ("DELETE", "/api/v2/filelib/clear/{knowledge_id}"),
    ("POST", "/api/v2/filelib/retrieve"),
    ("POST", "/api/v2/filelib/file/{knowledge_id}"),
    ("GET", "/api/v2/filelib/file/list"),
    ("DELETE", "/api/v2/filelib/file/{file_id}"),
    ("POST", "/api/v2/filelib/delete_file"),
}


def _principal(*, actor_kind="service_account", scopes=frozenset({"knowledge:read", "knowledge:write"})):
    natural_person = actor_kind == "natural_person"
    return OpenApiPrincipal(
        credential_id=1,
        actor_kind=actor_kind,
        actor_id=2,
        actor_name="caller",
        tenant_id=3,
        resource_owner_user_id=2,
        scopes=scopes,
        authorization_subject_type="user" if natural_person else "service_account",
        authorization_subject_id=2,
        effective_user_id=2 if natural_person else None,
    )


#: App-factory tools folded in from F052. They have no ``/api/v2`` source route,
#: so they stay out of ``SOURCE_ALLOWLIST`` and the API freeze contract.
APP_FACTORY_TOOLS = {
    "bisheng_identity_get_user",
    "bisheng_org_tree",
    "bisheng_dept_members",
    "bisheng_app_status",
    "bisheng_app_logs",
    "bisheng_app_db_tables",
    "bisheng_app_db_schema",
    "bisheng_app_db_rows",
    "bisheng_app_db_row_update",
}


def test_allowlist_is_exactly_ten_and_bidirectional():
    knowledge_tools = [item for item in TOOL_DEFINITIONS if item.name not in APP_FACTORY_TOOLS]
    assert len(knowledge_tools) == 10
    assert len(TOOL_DEFINITIONS) == len(TOOL_REGISTRY) == 10 + len(APP_FACTORY_TOOLS)
    assert SOURCE_ALLOWLIST == EXPECTED_SOURCES


def test_app_factory_tools_are_service_account_only_and_never_delegated():
    for name in APP_FACTORY_TOOLS:
        definition = TOOL_REGISTRY[name]
        assert definition.modes == frozenset({"S"})
        assert definition.allow_pat is False


def test_pat_only_discovers_the_three_read_tools():
    tools = list_tools_for(_principal(actor_kind="natural_person", scopes=frozenset({"knowledge:read"})))
    assert {tool.name for tool in tools} == {
        "bisheng_knowledge_list",
        "bisheng_knowledge_retrieve",
        "bisheng_knowledge_file_list",
    }


def test_service_account_discovery_obeys_scope():
    tools = list_tools_for(_principal(scopes=frozenset({"knowledge:write"})))
    assert len(tools) == 7
    assert all(TOOL_REGISTRY[tool.name].scope == "knowledge:write" for tool in tools)
