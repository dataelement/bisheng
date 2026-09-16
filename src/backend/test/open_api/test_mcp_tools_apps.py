"""F052 T208a / T209 — the application tools, and the one answer they give to "not yours".

The interesting property is negative: absent, another tenant's and somebody
else's must be **one** response carrying nothing but the ``app_id``. Anything
that distinguishes them — a different code, a different reason, the owner's
name — turns a developer key into a way to enumerate the tenant's applications.

The owner rule itself is not implemented in these tools. ⑥ passes ``entry="mcp"``
into the same services the CLI door uses; ⑤ passes nothing, because
``AppDataService`` builds owner-only in unconditionally. Two places deciding
"may this caller see it" is two places to drift.
"""

from __future__ import annotations

import pytest

from bisheng.common.errcode.app_factory import (
    AppDataForbiddenError,
    AppDataNotReadyError,
    AppLogForbiddenError,
    AppNotFoundError,
)
from bisheng.common.errcode.app_publish import AppNotOwnedBySubjectError, AppPublishOwnerOnlyError
from bisheng.open_api.mcp import registry

from .test_mcp_server import auth, error_payload, principal

APP_ID = "app-owned-by-the-key"


@pytest.fixture
def bearer(monkeypatch):
    def install(value):
        async def validate(_authorization):
            return value

        monkeypatch.setattr("bisheng.open_api.api.dependencies.validate_bearer", validate)

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


# --- ⑥ status and logs ------------------------------------------------------


async def test_status_returns_the_runtime_view_and_the_full_rejection_reason(bearer, mcp_session, services):
    bearer(principal(scopes=frozenset({"app:manage"})))
    async with mcp_session(auth()) as session:
        result = await session.call_tool("bisheng_app_status", {"app_id": APP_ID})

    assert not result.isError, result
    payload = result.structuredContent
    assert payload["app_id"] == APP_ID
    assert payload["instance"]["phase"] == "running"
    assert payload["publish"]["approval"]["reject_reason"] == "缺少健康检查"


async def test_status_and_logs_go_through_the_credential_door(bearer, mcp_session, services):
    """``entry="mcp"``, not a second owner comparison in the tool."""

    bearer(principal(scopes=frozenset({"app:manage"})))
    async with mcp_session(auth()) as session:
        await session.call_tool("bisheng_app_status", {"app_id": APP_ID})
        await session.call_tool("bisheng_app_logs", {"app_id": APP_ID})

    entries = {name: call["kwargs"].get("entry") for name, call in services.calls}
    assert entries["get_instance"] == "mcp"
    assert entries["get_publish_status"] == "mcp"
    assert entries["get_logs"] == "mcp"


async def test_the_actor_is_the_keys_resource_owner_and_carries_no_privilege(bearer, mcp_session, services):
    bearer(principal(scopes=frozenset({"app:manage"})))
    async with mcp_session(auth()) as session:
        await session.call_tool("bisheng_app_status", {"app_id": APP_ID})

    actor = dict(services.calls)["get_instance"]["kwargs"]["actor"]
    assert actor.user_id == 12  # resource_owner_user_id, not the service account id
    assert actor.user_role == []
    assert actor.is_global_super is False


async def test_logs_carry_the_two_fields_that_explain_an_empty_answer(bearer, mcp_session, services):
    """ "No lines" is a quiet app or a stopped one; the text alone cannot say which."""

    bearer(principal(scopes=frozenset({"app:manage"})))
    services.responses["get_logs"] = {"lines": []}
    services.responses["runtime_hint"] = {"app_state": "pending_capacity", "pending_reason": "capacity"}
    async with mcp_session(auth()) as session:
        result = await session.call_tool("bisheng_app_logs", {"app_id": APP_ID})

    assert result.structuredContent == {
        "lines": [],
        "app_state": "pending_capacity",
        "pending_reason": "capacity",
    }


@pytest.mark.parametrize(
    "failure",
    [
        AppNotFoundError(app_id=APP_ID),
        AppLogForbiddenError(app_id=APP_ID, entry="mcp"),
        AppPublishOwnerOnlyError(msg="x", details={"app_id": APP_ID, "reason": "not_visible"}),
        AppNotOwnedBySubjectError(msg="x", details={"reason": "resource_owner_missing"}),
    ],
)
async def test_every_not_yours_reason_gives_one_identical_answer(bearer, mcp_session, services, failure):
    """Absent, another tenant's, somebody else's, ownerless key — one payload."""

    bearer(principal(scopes=frozenset({"app:manage"})))
    services.responses["get_instance"] = failure
    async with mcp_session(auth()) as session:
        payload = error_payload(await session.call_tool("bisheng_app_status", {"app_id": APP_ID}))

    assert payload["code"] == 26305
    assert payload["category"] == "not_your_app"
    assert payload["data"] == {"app_id": APP_ID}


async def test_the_refusal_never_names_an_owner(bearer, mcp_session, services):
    import json

    bearer(principal(scopes=frozenset({"app:manage"})))
    services.responses["get_instance"] = AppPublishOwnerOnlyError(
        msg="没有查看该应用发布状态的权限",
        details={"app_id": APP_ID, "owner_user_name": "someone-else", "reason": "not_visible"},
    )
    async with mcp_session(auth()) as session:
        payload = error_payload(await session.call_tool("bisheng_app_status", {"app_id": APP_ID}))

    assert "someone-else" not in json.dumps(payload, ensure_ascii=False)
    assert "owner_user_name" not in json.dumps(payload)


# --- ⑤ application data -----------------------------------------------------


async def test_the_data_tools_pass_straight_through_to_the_data_service(bearer, mcp_session, services):
    bearer(principal(scopes=frozenset({"app:manage"})))
    async with mcp_session(auth()) as session:
        tables = await session.call_tool("bisheng_app_db_tables", {"app_id": APP_ID})
        schema = await session.call_tool("bisheng_app_db_schema", {"app_id": APP_ID, "table": "users"})
        rows = await session.call_tool("bisheng_app_db_rows", {"app_id": APP_ID, "table": "users"})
        updated = await session.call_tool(
            "bisheng_app_db_row_update",
            {"app_id": APP_ID, "table": "users", "key": "7", "values": {"name": "n"}},
        )

    assert tables.structuredContent["result"] == services.responses["list_tables"]
    assert schema.structuredContent["result"] == services.responses["get_table_schema"]
    assert rows.structuredContent["result"] == services.responses["get_rows"]
    assert updated.structuredContent["result"] == services.responses["update_row"]


async def test_the_data_tools_add_no_second_owner_check_and_no_entry(bearer, mcp_session, services):
    """``AppDataService`` builds owner-only in; a tool-level copy would drift."""

    bearer(principal(scopes=frozenset({"app:manage"})))
    async with mcp_session(auth()) as session:
        await session.call_tool("bisheng_app_db_tables", {"app_id": APP_ID})

    kwargs = dict(services.calls)["list_tables"]["kwargs"]
    assert "entry" not in kwargs
    assert kwargs["actor"].user_id == 12


async def test_an_application_with_no_database_yet_is_not_called_somebody_elses(bearer, mcp_session, services):
    """16163 is a real state of an application that *is* yours.

    Folding it into 26305 would tell a developer their own app is not theirs and
    send them to an administrator for nothing.
    """

    bearer(principal(scopes=frozenset({"app:manage"})))
    services.responses["list_tables"] = AppDataNotReadyError(app_id=APP_ID)
    async with mcp_session(auth()) as session:
        payload = error_payload(await session.call_tool("bisheng_app_db_tables", {"app_id": APP_ID}))

    assert payload["code"] == 16163
    assert payload["category"] == "unreachable"
    assert payload["next_step"]


async def test_a_data_permission_refusal_is_the_same_not_yours_answer(bearer, mcp_session, services):
    bearer(principal(scopes=frozenset({"app:manage"})))
    services.responses["list_tables"] = AppDataForbiddenError(app_id=APP_ID)
    async with mcp_session(auth()) as session:
        payload = error_payload(await session.call_tool("bisheng_app_db_tables", {"app_id": APP_ID}))

    assert payload["code"] == 26305
    assert payload["data"] == {"app_id": APP_ID}


def test_the_registry_offers_no_ddl_tool():
    """Schema is declared in ``bisheng-app.yaml`` and changed through the pipeline."""

    names = {spec.name for spec in registry.TOOL_REGISTRY}
    assert not any(verb in name for name in names for verb in ("create", "alter", "drop", "truncate"))


def test_the_tools_never_reach_the_orchestrator_directly():
    """The data plane goes backend service → orchestrator client → manager RPC."""

    import pathlib

    source = (
        pathlib.Path(__file__).resolve().parents[2] / "bisheng" / "open_api" / "mcp" / "tools" / "apps.py"
    ).read_text(encoding="utf-8")
    assert "orchestrator_client" not in source
    assert "runtime-manager" not in source


def test_personal_tokens_cannot_hold_the_scope_these_tools_need():
    """The first lock: a personal token is issued with exactly one scope, and it is not this one.

    ``requires_open_platform`` would not prove it — that flag is about whether
    the deployment carries the layer at all, not about who may hold the scope.
    """

    from bisheng.open_api.domain.services.personal_token_service import PERSONAL_TOKEN_SCOPE

    assert PERSONAL_TOKEN_SCOPE == "knowledge:read"
    assert PERSONAL_TOKEN_SCOPE != "app:manage"


async def test_a_key_with_no_resource_owner_gets_the_same_one_answer(bearer, mcp_session, services):
    """The second lock, and it must not answer in a different shape than the first.

    ``resource_owner_of`` raises 16205 before any service is reached. That is
    still "no application you can reach": folding it here keeps the payload a
    bare ``app_id`` instead of leaking the error's own ``details`` / ``hints``.
    """

    import json

    ownerless = principal(scopes=frozenset({"app:manage"})).model_copy(update={"resource_owner_user_id": None})
    bearer(ownerless)
    async with mcp_session(auth()) as session:
        status = error_payload(await session.call_tool("bisheng_app_status", {"app_id": APP_ID}))
        logs = error_payload(await session.call_tool("bisheng_app_logs", {"app_id": APP_ID}))

    assert status["code"] == 26305
    assert status["data"] == {"app_id": APP_ID}
    assert status == logs
    assert "resource_owner_missing" not in json.dumps(status, ensure_ascii=False)
