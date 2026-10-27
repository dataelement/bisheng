"""The hosted-application MCP tools (F052 T208a / T209, served by F067 ``open_mcp``).

The interesting property is negative: absent, another tenant's and somebody
else's must be **one** response carrying nothing but the ``app_id``. Anything
that distinguishes them — a different code, a different reason, the owner's
name — turns a developer key into a way to enumerate the tenant's applications.

The owner rule itself is not implemented in these tools. Status and logs pass
``entry="mcp"`` into the same services the CLI door uses; the data tools pass
nothing, because ``AppDataService`` builds owner-only in unconditionally. Two
places deciding "may this caller see it" is two places to drift.
"""

from __future__ import annotations

import json

import pytest

from bisheng.common.errcode.app_factory import (
    AppDataForbiddenError,
    AppDataNotReadyError,
    AppLogForbiddenError,
    AppNotFoundError,
)
from bisheng.common.errcode.app_publish import (
    AppNotOwnedBySubjectError,
    AppPublishOwnerOnlyError,
    AppPublishRuntimeLayerDisabledError,
)
from bisheng.common.errcode.mcp_face import McpAppNotOwnedError
from bisheng.open_api.domain.context import OpenApiPrincipal
from bisheng.open_mcp import registry
from bisheng.open_mcp.result import error_result_from_exception
from bisheng.open_mcp.tools import execute_tool

APP_ID = "app-owned-by-the-key"
APP_TOOLS = {
    "bisheng_app_status",
    "bisheng_app_logs",
    "bisheng_app_db_tables",
    "bisheng_app_db_schema",
    "bisheng_app_db_rows",
    "bisheng_app_db_row_update",
}


def principal(*, scopes=frozenset({"app:manage"}), owner=12, actor_kind="service_account") -> OpenApiPrincipal:
    return OpenApiPrincipal(
        credential_id=7,
        actor_kind=actor_kind,
        actor_id=31,
        actor_name="indexer",
        tenant_id=9,
        resource_owner_user_id=owner,
        scopes=frozenset(scopes),
        authorization_subject_type="service_account" if actor_kind == "service_account" else "user",
        authorization_subject_id=31 if actor_kind == "service_account" else 12,
        effective_user_id=None if actor_kind == "service_account" else 12,
    )


@pytest.fixture
def as_principal(monkeypatch):
    """Answer ``get_current_open_api_principal`` with the principal you hand it.

    Patched rather than set on the ContextVar: an async test runs in its own
    context, so a token from a sync fixture cannot be reset there.
    """

    def install(value: OpenApiPrincipal) -> None:
        monkeypatch.setattr("bisheng.open_mcp.tools.apps.get_current_open_api_principal", lambda: value)

    return install


@pytest.fixture(autouse=True)
def runtime_on(monkeypatch):
    monkeypatch.setattr(registry.settings.app_runtime, "enabled", True)


@pytest.fixture
def services(monkeypatch):
    """Programmable stand-ins for the three services the tools call."""

    from bisheng.app_publish.domain.services.publish_status_service import PublishStatusService
    from bisheng.app_runtime.domain.services.app_data_service import AppDataService
    from bisheng.app_runtime.domain.services.app_query_service import AppQueryService

    calls: list[tuple[str, dict]] = []
    responses: dict[str, object] = {
        "get_instance": {"instance_id": "inst-1", "phase": "running", "health": "healthy"},
        "get_publish_status": {"app_id": APP_ID, "app_state": "online", "approval": {"reject_reason": "缺少健康检查"}},
        "get_logs": {"lines": ["boot ok"]},
        "runtime_hint": {"app_state": "online", "pending_reason": None},
        "list_tables": {"tables": [{"name": "users", "column_count": 2}]},
        "get_table_schema": {"table": "users", "columns": [], "key": {"column": "id"}, "editable": True},
        "get_rows": {"rows": [], "total": 0},
        "update_row": {"updated": 1},
    }

    def stub(name, owner=PublishStatusService):
        async def call(*args, **kwargs):
            calls.append((name, {"args": args, "kwargs": kwargs}))
            value = responses[name]
            if isinstance(value, Exception):
                raise value
            return value

        return call

    monkeypatch.setattr(AppQueryService, "get_instance", stub("get_instance"))
    monkeypatch.setattr(AppQueryService, "get_logs", stub("get_logs"))
    monkeypatch.setattr(PublishStatusService, "get_publish_status", stub("get_publish_status"))
    monkeypatch.setattr(PublishStatusService, "runtime_hint", stub("runtime_hint"))
    for name in ("list_tables", "get_table_schema", "get_rows", "update_row"):
        monkeypatch.setattr(AppDataService, name, stub(name))

    return type("Services", (), {"calls": calls, "responses": responses})()


# --- status and logs ----------------------------------------------------------


async def test_status_returns_the_runtime_view_and_the_full_rejection_reason(as_principal, services):
    as_principal(principal())
    result = await execute_tool("bisheng_app_status", {"app_id": APP_ID})

    assert result.app_id == APP_ID
    assert result.instance["phase"] == "running"
    assert result.publish["approval"]["reject_reason"] == "缺少健康检查"


async def test_status_and_logs_go_through_the_credential_door(as_principal, services):
    """``entry="mcp"``, not a second owner comparison in the tool."""

    as_principal(principal())
    await execute_tool("bisheng_app_status", {"app_id": APP_ID})
    await execute_tool("bisheng_app_logs", {"app_id": APP_ID})

    entries = {name: call["kwargs"].get("entry") for name, call in services.calls}
    assert entries["get_instance"] == "mcp"
    assert entries["get_publish_status"] == "mcp"
    assert entries["get_logs"] == "mcp"


async def test_the_actor_is_the_keys_resource_owner_and_carries_no_privilege(as_principal, services):
    as_principal(principal())
    await execute_tool("bisheng_app_status", {"app_id": APP_ID})

    actor = dict(services.calls)["get_instance"]["kwargs"]["actor"]
    assert actor.user_id == 12  # resource_owner_user_id, not the service account id
    assert actor.user_role == []
    assert actor.is_global_super is False


async def test_logs_carry_the_two_fields_that_explain_an_empty_answer(as_principal, services):
    """ "No lines" is a quiet app or a stopped one; the text alone cannot say which."""

    as_principal(principal())
    services.responses["get_logs"] = {"lines": []}
    services.responses["runtime_hint"] = {"app_state": "pending_capacity", "pending_reason": "capacity"}
    result = await execute_tool("bisheng_app_logs", {"app_id": APP_ID})

    assert result.model_dump() == {"lines": [], "app_state": "pending_capacity", "pending_reason": "capacity"}


@pytest.mark.parametrize(
    "failure",
    [
        AppNotFoundError(app_id=APP_ID),
        AppLogForbiddenError(app_id=APP_ID, entry="mcp"),
        AppPublishOwnerOnlyError(msg="x", details={"app_id": APP_ID, "reason": "not_visible"}),
        AppNotOwnedBySubjectError(msg="x", details={"reason": "resource_owner_missing"}),
    ],
)
async def test_every_not_yours_reason_gives_one_identical_answer(as_principal, services, failure):
    """Absent, another tenant's, somebody else's, ownerless key — one payload."""

    as_principal(principal())
    services.responses["get_instance"] = failure
    with pytest.raises(McpAppNotOwnedError) as refused:
        await execute_tool("bisheng_app_status", {"app_id": APP_ID})

    assert refused.value.code == 26305
    assert refused.value.kwargs == {"app_id": APP_ID}


async def test_the_refusal_never_names_an_owner(as_principal, services):
    as_principal(principal())
    services.responses["get_instance"] = AppPublishOwnerOnlyError(
        msg="没有查看该应用发布状态的权限",
        details={"app_id": APP_ID, "owner_user_name": "someone-else", "reason": "not_visible"},
    )
    with pytest.raises(McpAppNotOwnedError) as refused:
        await execute_tool("bisheng_app_status", {"app_id": APP_ID})

    rendered = error_result_from_exception(refused.value).content[0].text
    assert "someone-else" not in rendered
    assert "owner_user_name" not in rendered


# --- application data ---------------------------------------------------------


async def test_the_data_tools_pass_straight_through_to_the_data_service(as_principal, services):
    as_principal(principal())
    tables = await execute_tool("bisheng_app_db_tables", {"app_id": APP_ID})
    schema = await execute_tool("bisheng_app_db_schema", {"app_id": APP_ID, "table": "users"})
    rows = await execute_tool("bisheng_app_db_rows", {"app_id": APP_ID, "table": "users"})
    updated = await execute_tool(
        "bisheng_app_db_row_update",
        {"app_id": APP_ID, "table": "users", "key": "7", "values": {"name": "n"}},
    )

    assert tables.result == services.responses["list_tables"]
    assert schema.result == services.responses["get_table_schema"]
    assert rows.result == services.responses["get_rows"]
    assert updated.result == services.responses["update_row"]


async def test_the_data_tools_add_no_second_owner_check_and_no_entry(as_principal, services):
    """``AppDataService`` builds owner-only in; a tool-level copy would drift."""

    as_principal(principal())
    await execute_tool("bisheng_app_db_tables", {"app_id": APP_ID})

    kwargs = dict(services.calls)["list_tables"]["kwargs"]
    assert "entry" not in kwargs
    assert kwargs["actor"].user_id == 12


async def test_an_application_with_no_database_yet_is_not_called_somebody_elses(as_principal, services):
    """16163 is a real state of an application that *is* yours.

    Folding it into 26305 would tell a developer their own app is not theirs and
    send them to an administrator for nothing.
    """

    as_principal(principal())
    services.responses["list_tables"] = AppDataNotReadyError(app_id=APP_ID)
    with pytest.raises(AppDataNotReadyError) as refused:
        await execute_tool("bisheng_app_db_tables", {"app_id": APP_ID})
    assert refused.value.code == 16163


async def test_a_data_permission_refusal_is_the_same_not_yours_answer(as_principal, services):
    as_principal(principal())
    services.responses["list_tables"] = AppDataForbiddenError(app_id=APP_ID)
    with pytest.raises(McpAppNotOwnedError) as refused:
        await execute_tool("bisheng_app_db_tables", {"app_id": APP_ID})
    assert refused.value.kwargs == {"app_id": APP_ID}


async def test_a_key_with_no_resource_owner_gets_the_same_one_answer(as_principal, services):
    """``resource_owner_of`` raises 16205 before any service is reached.

    That is still "no application you can reach": folding it keeps the payload a
    bare ``app_id`` instead of leaking the error's own ``details`` / ``hints``.
    """

    as_principal(principal(owner=None))
    with pytest.raises(McpAppNotOwnedError) as status:
        await execute_tool("bisheng_app_status", {"app_id": APP_ID})
    with pytest.raises(McpAppNotOwnedError) as logs:
        await execute_tool("bisheng_app_logs", {"app_id": APP_ID})

    assert status.value.to_dict() == logs.value.to_dict()
    assert "resource_owner_missing" not in json.dumps(status.value.to_dict(), ensure_ascii=False)


# --- registry: who may see these tools ---------------------------------------


def test_the_registry_offers_no_ddl_tool():
    """Schema is declared in ``bisheng-app.yaml`` and changed through the pipeline."""

    names = set(registry.TOOL_REGISTRY)
    assert not any(verb in name for name in names for verb in ("create_table", "alter", "drop", "truncate"))


def test_the_tools_are_listed_for_a_key_with_the_scope():
    listed = {tool.name for tool in registry.list_tools_for(principal())}
    assert APP_TOOLS <= listed


def test_a_delegated_key_never_sees_the_local_development_tools():
    """INV-31: these tools run as the service account itself, never on behalf of anyone."""

    delegated = principal(scopes=frozenset({"app:manage", "identity:read", "delegate"}))
    listed = {tool.name for tool in registry.list_tools_for(delegated)}

    assert not (APP_TOOLS & listed)
    assert "bisheng_org_tree" not in listed
    assert not registry.TOOL_REGISTRY["bisheng_app_status"].visible_to(delegated)


def test_personal_tokens_never_see_the_app_tools():
    pat = principal(actor_kind="natural_person")
    assert not (APP_TOOLS & {tool.name for tool in registry.list_tools_for(pat)})


def test_without_the_runtime_layer_the_tools_are_not_listed(monkeypatch):
    monkeypatch.setattr(registry.settings.app_runtime, "enabled", False)
    assert not (APP_TOOLS & {tool.name for tool in registry.list_tools_for(principal())})


async def test_without_the_runtime_layer_a_direct_call_is_refused(monkeypatch, as_principal, services):
    monkeypatch.setattr(registry.settings.app_runtime, "enabled", False)
    as_principal(principal())
    with pytest.raises(AppPublishRuntimeLayerDisabledError):
        await execute_tool("bisheng_app_status", {"app_id": APP_ID})
    assert services.calls == []


def test_the_tools_never_reach_the_orchestrator_directly():
    """The data plane goes backend service → orchestrator client → manager RPC."""

    import pathlib

    source = (pathlib.Path(__file__).resolve().parents[2] / "bisheng" / "open_mcp" / "tools" / "apps.py").read_text(
        encoding="utf-8"
    )
    assert "orchestrator_client" not in source
    assert "runtime-manager" not in source


def test_personal_tokens_cannot_hold_the_scope_these_tools_need():
    from bisheng.open_api.domain.services.personal_token_service import PERSONAL_TOKEN_SCOPE

    assert PERSONAL_TOKEN_SCOPE == "knowledge:read"
