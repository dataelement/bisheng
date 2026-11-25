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
    ("POST", "/api/v2/filelib/query_qa"),
    ("GET", "/api/v2/filelib/detail_qa"),
    ("POST", "/api/v2/filelib/add_qa"),
    ("POST", "/api/v2/filelib/add_relative_qa"),
    ("POST", "/api/v2/filelib/update_qa"),
    ("DELETE", "/api/v2/filelib/qa/{qa_id}"),
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


def test_allowlist_is_exactly_sixteen_and_bidirectional():
    assert len(TOOL_DEFINITIONS) == len(TOOL_REGISTRY) == 16
    assert SOURCE_ALLOWLIST == EXPECTED_SOURCES


def test_pat_only_discovers_the_read_tools():
    tools = list_tools_for(_principal(actor_kind="natural_person", scopes=frozenset({"knowledge:read"})))
    assert {tool.name for tool in tools} == {
        "bisheng_knowledge_list",
        "bisheng_knowledge_retrieve",
        "bisheng_knowledge_file_list",
        "bisheng_knowledge_qa_query",
        "bisheng_knowledge_qa_detail",
    }


def test_service_account_discovery_obeys_scope():
    tools = list_tools_for(_principal(scopes=frozenset({"knowledge:write"})))
    assert len(tools) == 11
    assert all(TOOL_REGISTRY[tool.name].scope == "knowledge:write" for tool in tools)
