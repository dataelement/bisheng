"""F052 T203a — the MCP transport, its gate, and the tool dispatcher.

Most of this drives a **real** ``ClientSession`` over the ASGI app. The one
acceptance criterion this face exists for ("any standard MCP client connects with
no changes") cannot be checked by hand-rolled JSON-RPC posts: those would keep
passing with a broken handshake. ``mcp_http`` is for the transport-level facts a
protocol client hides — status codes, redirects, the ``Host`` header.
"""

from __future__ import annotations

import json

import httpx
import pytest

from bisheng.common.errcode.open_api import OpenApiCredentialInvalidError, OpenApiCredentialMissingError
from bisheng.core.context.tenant import get_current_tenant_id, get_visible_tenant_ids
from bisheng.open_api.domain.context import OpenApiPrincipal
from bisheng.open_api.mcp import registry
from bisheng.open_api.mcp.errors import ERROR_CATEGORY_MAP, NEXT_STEP_COPY, SUPPORTED_LANGS

ALL_SCOPES = frozenset({"knowledge:read", "model:invoke", "identity:read", "app:manage"})
JSON_RPC_ACCEPT = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def principal(*, scopes=ALL_SCOPES, actor_kind="service_account", delegate=False) -> OpenApiPrincipal:
    codes = set(scopes)
    if delegate:
        codes.add("delegate")
    return OpenApiPrincipal(
        credential_id=7,
        actor_kind=actor_kind,
        actor_id=31,
        actor_name="indexer",
        tenant_id=9,
        resource_owner_user_id=12,
        scopes=frozenset(codes),
        authorization_subject_type="service_account" if actor_kind == "service_account" else "user",
        authorization_subject_id=31 if actor_kind == "service_account" else 12,
        effective_user_id=None if actor_kind == "service_account" else 12,
    )


@pytest.fixture
def bearer(monkeypatch):
    """Install a ``validate_bearer`` answering with the principal you hand it."""

    def install(value):
        async def validate(_authorization):
            if value is None:
                raise OpenApiCredentialInvalidError()
            return value

        monkeypatch.setattr("bisheng.open_api.api.dependencies.validate_bearer", validate)

    return install


@pytest.fixture
def runtime_layer(monkeypatch):
    def install(enabled: bool):
        monkeypatch.setattr(registry.settings.app_runtime, "enabled", enabled)

    return install


def auth(token: str = "bs-sak-secret-value") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", **JSON_RPC_ACCEPT}


def rpc(method: str, params: dict | None = None, *, request_id: int = 1) -> dict:
    payload = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        payload["params"] = params
    return payload


def tool_names(result) -> set[str]:
    return {tool.name for tool in result.tools}


def error_payload(result) -> dict:
    """The three-part JSON an agent is supposed to be able to parse.

    ``json.loads`` on the text, not merely ``isError`` — ``Tool.run`` prefixes
    handler exceptions with ``Error executing tool <name>:`` and that alone would
    make every payload unparseable while ``isError`` stayed happily true (pit 19).
    """

    assert result.isError, result
    text = "".join(getattr(block, "text", "") for block in result.content)
    return json.loads(text)


# --- credentials -----------------------------------------------------------


async def test_no_credential_is_refused_at_the_handshake(mcp_http, monkeypatch):
    async def validate(_authorization):
        raise OpenApiCredentialMissingError()

    monkeypatch.setattr("bisheng.open_api.api.dependencies.validate_bearer", validate)
    async with mcp_http(JSON_RPC_ACCEPT) as client:
        response = await client.post("/api/v2/mcp", json=rpc("tools/list"))
    assert response.status_code == 401
    assert response.json()["status_code"] == 26001


async def test_invalid_or_revoked_credential_cannot_even_initialise(bearer, mcp_session):
    """AC-02 from the client's side: the handshake itself fails, so nothing is listed.

    The SDK surfaces transport failures through its task group, so the 401 comes
    back wrapped in an ``ExceptionGroup`` — unwrapped here rather than matched
    loosely, or a future crash inside the handshake would also pass.
    """

    bearer(None)
    with pytest.raises(BaseExceptionGroup) as raised:
        async with mcp_session(auth()):
            pass

    assert [error.response.status_code for error in _http_errors(raised.value)] == [401]


def _http_errors(exc: BaseException) -> list[httpx.HTTPStatusError]:
    """Flatten a (possibly nested) exception group down to the HTTP failures."""

    if isinstance(exc, BaseExceptionGroup):
        return [error for child in exc.exceptions for error in _http_errors(child)]
    return [exc] if isinstance(exc, httpx.HTTPStatusError) else []


async def test_query_parameter_token_is_not_a_credential(mcp_http, monkeypatch):
    """Only the Authorization header counts — a query string lands in access logs."""

    seen: list[str | None] = []

    async def validate(authorization):
        seen.append(authorization)
        raise OpenApiCredentialMissingError()

    monkeypatch.setattr("bisheng.open_api.api.dependencies.validate_bearer", validate)
    async with mcp_http(JSON_RPC_ACCEPT) as client:
        response = await client.post(
            "/api/v2/mcp?token=bs-sak-secret&authorization=Bearer+bs-sak-secret",
            json=rpc("tools/list"),
        )
    assert response.status_code == 401
    assert seen == [None]


async def test_bare_path_is_not_redirected(mcp_http, bearer):
    """``/api/v2/mcp`` answers directly. A ``Mount`` would 307 to the trailing slash.

    The official Python client follows redirects, so a ``Mount`` would look fine
    there while costing every other client an extra round trip — or breaking
    outright behind a gateway that does not follow a 307 on POST.
    """

    bearer(principal())
    async with mcp_http(auth(), follow_redirects=False) as client:
        response = await client.post("/api/v2/mcp", json=rpc("tools/list"))
    assert response.status_code not in (301, 302, 307, 308)
    assert response.status_code == 200


async def test_real_host_header_is_accepted(mcp_http, bearer):
    """DNS-rebinding protection would 421 every request nginx forwards."""

    bearer(principal())
    async with mcp_http({**auth(), "Host": "192.168.106.114:4101"}) as client:
        response = await client.post("/api/v2/mcp", json=rpc("tools/list"))
    assert response.status_code == 200


# --- delegation and identity headers ---------------------------------------


async def test_delegate_key_is_refused_at_the_door(mcp_http, bearer):
    bearer(principal(delegate=True))
    async with mcp_http(auth()) as client:
        response = await client.post("/api/v2/mcp", json=rpc("tools/list"))
    assert response.status_code == 403
    assert response.json()["status_code"] == 26051


async def test_delegate_key_never_falls_back_to_running_as_the_service_account(mcp_http, bearer):
    """Not 26016 "send X-On-Behalf-Of", and emphatically not a successful call."""

    bearer(principal(delegate=True))
    async with mcp_http(auth()) as client:
        response = await client.post(
            "/api/v2/mcp", json=rpc("tools/call", {"name": "bisheng_org_tree", "arguments": {}})
        )
    assert response.status_code == 403
    assert response.json()["status_code"] == 26051


@pytest.mark.parametrize("header", ["X-On-Behalf-Of", "X-End-User", "X-Gateway-On-Behalf-Of", "x-end-user"])
async def test_identity_headers_are_refused_not_ignored(mcp_http, bearer, header):
    bearer(principal())
    async with mcp_http({**auth(), header: "12"}) as client:
        response = await client.post("/api/v2/mcp", json=rpc("tools/list"))
    assert response.status_code == 403
    assert response.json()["status_code"] == 26303


# --- tool listing ----------------------------------------------------------


async def test_list_tools_is_filtered_by_scope(bearer, mcp_session, runtime_layer):
    runtime_layer(True)
    bearer(principal(scopes=frozenset({"identity:read"})))
    async with mcp_session(auth()) as session:
        listed = tool_names(await session.list_tools())
    assert listed == {"bisheng_identity_get_user", "bisheng_org_tree", "bisheng_dept_members"}


async def test_empty_scopes_still_handshakes_and_lists_nothing(bearer, mcp_session):
    """Connecting is not a capability — refusing the handshake would read as a broken key."""

    bearer(principal(scopes=frozenset()))
    async with mcp_session(auth()) as session:
        assert tool_names(await session.list_tools()) == set()
        result = await session.call_tool("bisheng_org_tree", {})
    assert error_payload(result)["code"] == 26302


async def test_calling_an_unlisted_tool_names_the_missing_scope(bearer, mcp_session):
    bearer(principal(scopes=frozenset({"knowledge:read"})))
    async with mcp_session(auth()) as session:
        result = await session.call_tool("bisheng_org_tree", {})
    payload = error_payload(result)
    assert payload["code"] == 26302
    assert payload["category"] == "scope_missing"
    assert payload["data"]["required"] == "identity:read"
    assert payload["next_step"]


async def test_unknown_tool_is_not_confused_with_a_missing_scope(bearer, mcp_session):
    bearer(principal())
    async with mcp_session(auth()) as session:
        result = await session.call_tool("bisheng_definitely_not_a_tool", {})
    assert error_payload(result)["code"] == 26301


async def test_scope_edit_takes_effect_on_the_next_call_without_reconnecting(monkeypatch, mcp_session, runtime_layer):
    runtime_layer(True)
    state = {"principal": principal(scopes=frozenset({"identity:read"}))}

    async def validate(_authorization):
        return state["principal"]

    monkeypatch.setattr("bisheng.open_api.api.dependencies.validate_bearer", validate)
    async with mcp_session(auth()) as session:
        assert "bisheng_app_status" not in tool_names(await session.list_tools())
        state["principal"] = principal(scopes=frozenset({"identity:read", "app:manage"}))
        assert "bisheng_app_status" in tool_names(await session.list_tools())


async def test_application_tools_are_absent_when_the_runtime_layer_is_off(bearer, mcp_session, runtime_layer):
    runtime_layer(False)
    bearer(principal(scopes=frozenset({"app:manage"})))
    async with mcp_session(auth()) as session:
        assert tool_names(await session.list_tools()) == set()
        result = await session.call_tool("bisheng_app_status", {"app_id": "app-1"})
    payload = error_payload(result)
    assert payload["code"] == 16207
    assert payload["category"] == "runtime_disabled"


# --- execution identity ----------------------------------------------------


async def test_the_handler_runs_under_the_credentials_tenant(bearer, mcp_session, monkeypatch):
    """The transport starts the tool in a task of the lifespan's task group.

    ContextVars are copied at task creation, so the gate's installation does
    reach the handler — but that is a property of the SDK's internals rather
    than of our code, and exactly the sort of thing a version bump breaks
    silently.
    """

    seen: dict[str, object] = {}

    async def spy():
        seen["tenant"] = get_current_tenant_id()
        seen["visible"] = set(get_visible_tenant_ids())
        return []

    monkeypatch.setattr("bisheng.open_api.mcp.tools.identity.OrgDirectoryService.atree", staticmethod(spy))
    bearer(principal(scopes=frozenset({"identity:read"})))
    async with mcp_session(auth()) as session:
        await session.call_tool("bisheng_org_tree", {})

    assert seen["tenant"] == 9
    assert seen["visible"] == {1, 9}


async def test_no_key_material_appears_in_any_response(mcp_http, bearer):
    bearer(principal(scopes=frozenset({"knowledge:read"})))
    async with mcp_http(auth()) as client:
        listed = await client.post("/api/v2/mcp", json=rpc("tools/list"))
        refused = await client.post(
            "/api/v2/mcp",
            json=rpc("tools/call", {"name": "bisheng_org_tree", "arguments": {}}, request_id=2),
        )
    for response in (listed, refused):
        assert "bs-sak-" not in response.text
        assert "bs-pat-" not in response.text


async def test_the_face_touches_no_platform_session(bearer, mcp_session, monkeypatch):
    """An MCP connection is a protocol session, never a conversation (AC-08).

    Both halves matter: nothing in the package *names* the session DAOs, and a
    live handshake plus listing plus a call reaches none of them either.
    """

    from bisheng.database.models.session import MessageSessionDao

    def explode(*_args, **_kwargs):
        raise AssertionError("the MCP face must not read or write platform sessions")

    for name in dir(MessageSessionDao):
        if name.startswith(("a", "insert", "get", "update", "delete")) and callable(
            getattr(MessageSessionDao, name, None)
        ):
            monkeypatch.setattr(MessageSessionDao, name, explode, raising=False)

    async def tree():
        return []

    monkeypatch.setattr("bisheng.open_api.mcp.tools.identity.OrgDirectoryService.atree", staticmethod(tree))
    bearer(principal(scopes=frozenset({"identity:read"})))
    async with mcp_session(auth()) as session:
        await session.list_tools()
        await session.call_tool("bisheng_org_tree", {})


def test_the_face_does_not_even_import_session_modules():
    """The structural half of AC-08 — a grep a reviewer would otherwise have to run."""

    import pathlib

    package = pathlib.Path(__file__).resolve().parents[2] / "bisheng" / "open_api" / "mcp"
    sources = list(package.rglob("*.py"))
    assert sources
    forbidden = ("chat_session", "MessageSessionDao", "ChatMessageDao", "message_session")
    offenders = [
        (path.name, needle) for path in sources for needle in forbidden if needle in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


# --- error shape -----------------------------------------------------------


def test_every_mapped_code_has_three_language_next_step_copy():
    assert set(ERROR_CATEGORY_MAP) == set(NEXT_STEP_COPY)
    for code, copy in NEXT_STEP_COPY.items():
        assert set(copy) == set(SUPPORTED_LANGS), code
        assert all(copy[lang].strip() for lang in SUPPORTED_LANGS), code


async def test_accept_language_picks_the_next_step_language(bearer, mcp_session):
    bearer(principal(scopes=frozenset({"knowledge:read"})))
    async with mcp_session({**auth(), "Accept-Language": "en-US,en;q=0.9"}) as session:
        english = error_payload(await session.call_tool("bisheng_org_tree", {}))
    async with mcp_session(auth()) as session:
        chinese = error_payload(await session.call_tool("bisheng_org_tree", {}))

    assert english["next_step"] == NEXT_STEP_COPY[26302]["en"]
    assert chinese["next_step"] == NEXT_STEP_COPY[26302]["zh-Hans"]


async def test_tool_error_text_is_parseable_json_with_all_three_parts(bearer, mcp_session):
    bearer(principal(scopes=frozenset({"knowledge:read"})))
    async with mcp_session(auth()) as session:
        result = await session.call_tool("bisheng_org_tree", {})
    payload = error_payload(result)
    assert set(payload) == {"code", "category", "reason", "next_step", "data"}


async def test_a_handler_failure_keeps_the_three_part_shape(bearer, mcp_session, monkeypatch):
    """Pit 19: ``Tool.run`` re-wraps handler exceptions and would break the JSON."""

    from bisheng.common.errcode.mcp_face import McpIdentityNotFoundError

    async def boom(_user_id):
        raise McpIdentityNotFoundError()

    monkeypatch.setattr("bisheng.open_api.mcp.tools.identity.OrgDirectoryService.aget_user", staticmethod(boom))
    bearer(principal(scopes=frozenset({"identity:read"})))
    async with mcp_session(auth()) as session:
        result = await session.call_tool("bisheng_identity_get_user", {"user_id": 5})
    payload = error_payload(result)
    assert payload["code"] == 26306
    assert payload["category"] == "unreachable"


async def test_an_unmapped_failure_never_leaks_its_message(bearer, mcp_session, monkeypatch):
    async def boom():
        raise RuntimeError("/var/lib/secret/path: connection string postgres://u:p@h/db")

    monkeypatch.setattr("bisheng.open_api.mcp.tools.identity.OrgDirectoryService.atree", staticmethod(boom))
    bearer(principal(scopes=frozenset({"identity:read"})))
    async with mcp_session(auth()) as session:
        result = await session.call_tool("bisheng_org_tree", {})
    payload = error_payload(result)
    assert payload["category"] == "internal"
    assert "postgres" not in json.dumps(payload)
    assert "/var/lib" not in json.dumps(payload)


async def test_bad_arguments_are_a_structured_refusal_not_a_crash(bearer, mcp_session):
    bearer(principal(scopes=frozenset({"identity:read"})))
    async with mcp_session(auth()) as session:
        result = await session.call_tool("bisheng_identity_get_user", {"user_id": "not-an-int"})
    assert result.isError


async def test_a_successful_call_carries_structured_content(bearer, mcp_session, monkeypatch):
    """Pit 20: an output that does not match its schema becomes a bare text error.

    That bypasses the whole three-part error layer, so it reads as a tool which
    mysteriously answers in prose. Asserting ``structuredContent`` is how drift
    between a handler and its output model surfaces as a test failure instead.
    """

    async def tree():
        return [
            {
                "dept_id": "BS@a1",
                "name": "Engineering",
                "parent_id": None,
                "path": "/1/",
                "sort_order": 0,
                "source": "local",
                "status": "active",
                "children": [],
            }
        ]

    monkeypatch.setattr("bisheng.open_api.mcp.tools.identity.OrgDirectoryService.atree", staticmethod(tree))
    bearer(principal(scopes=frozenset({"identity:read"})))
    async with mcp_session(auth()) as session:
        result = await session.call_tool("bisheng_org_tree", {})

    assert not result.isError, result
    assert result.structuredContent
    assert "Output validation error" not in "".join(getattr(block, "text", "") for block in result.content)
    assert result.structuredContent["departments"][0]["dept_id"] == "BS@a1"


async def test_listed_tools_publish_an_output_schema(bearer, mcp_session, runtime_layer):
    """Without it an agent has to guess the result shape from prose."""

    runtime_layer(True)
    bearer(principal())
    async with mcp_session(auth()) as session:
        listed = (await session.list_tools()).tools
    assert listed
    for tool in listed:
        assert tool.outputSchema, tool.name
        assert tool.inputSchema is not None, tool.name
