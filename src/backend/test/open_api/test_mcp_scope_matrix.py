"""F052 T212 — every tool against every single-scope key, generated from the registry.

Hand-written per-tool cases are exactly how one tool ends up callable by a key
that should not have it: nobody notices the missing case. This walks the
registry instead, so a tool added without a matrix entry fails the last test in
this file rather than shipping unchecked.

The denominator is the **available** tools, not the whole table: ③ and the
knowledge tools stay hidden until F051's resolver and the retrieval facade land,
and a fixed denominator would make CI red for the whole staged rollout.
"""

from __future__ import annotations

import pytest

from bisheng.open_api.mcp import registry

from .test_mcp_server import auth, error_payload, principal

SCOPES = ("knowledge:read", "model:invoke", "identity:read", "app:manage")
#: The fifth column: a key with nothing ticked. It completes the handshake and
#: can call nothing — the same state ``bisheng login`` leaves a fresh key in.
KEYS = (*SCOPES, None)

AVAILABLE = tuple(registry.installed_tools())
CASES = [(spec, held) for spec in AVAILABLE for held in KEYS]


def _ids(case):
    spec, held = case
    return f"{spec.name}-{held or 'no-scope'}"


@pytest.fixture(autouse=True)
def runtime_on(monkeypatch):
    """The matrix is about scopes; the runtime-layer switch has its own tests."""

    monkeypatch.setattr(registry.settings.app_runtime, "enabled", True)


@pytest.fixture
def bearer(monkeypatch):
    def install(value):
        async def validate(_authorization):
            return value

        monkeypatch.setattr("bisheng.open_api.api.dependencies.validate_bearer", validate)

    return install


@pytest.fixture(autouse=True)
def quiet_services(monkeypatch):
    """Answer at the **service** boundary, so the handlers themselves still run.

    Stubbing the handlers instead would prove only that the registry can find a
    name. Letting them reach a database, on the other hand, is not an option
    here: with no middleware the session fails mid-flight and leaves the engine
    in a state that breaks *later* files in the same run — which is how this
    matrix once turned ``test_route_error_contract`` red from three files away.
    """

    from bisheng.app_publish.domain.services.publish_status_service import PublishStatusService
    from bisheng.app_runtime.domain.services.app_data_service import AppDataService
    from bisheng.app_runtime.domain.services.app_query_service import AppQueryService
    from bisheng.department.domain.services.org_directory_service import OrgDirectoryService

    async def empty_list(*_args, **_kwargs):
        return []

    async def empty_dict(*_args, **_kwargs):
        return {}

    async def members(*_args, **_kwargs):
        return {"members": [], "total": 0}

    async def user(*_args, **_kwargs):
        return {"user_id": 1, "user_name": "x", "status": "active", "departments": [], "roles": []}

    async def logs(*_args, **_kwargs):
        return {"lines": []}

    for target, replacement in (
        ((OrgDirectoryService, "atree"), empty_list),
        ((OrgDirectoryService, "amembers"), members),
        ((OrgDirectoryService, "aget_user"), user),
        ((AppQueryService, "get_instance"), empty_dict),
        ((AppQueryService, "get_logs"), logs),
        ((PublishStatusService, "get_publish_status"), empty_dict),
        ((PublishStatusService, "runtime_hint"), empty_dict),
        ((AppDataService, "list_tables"), empty_dict),
        ((AppDataService, "get_table_schema"), empty_dict),
        ((AppDataService, "get_rows"), empty_dict),
        ((AppDataService, "update_row"), empty_dict),
    ):
        monkeypatch.setattr(target[0], target[1], replacement)


@pytest.mark.parametrize(("spec", "held"), CASES, ids=[_ids(case) for case in CASES])
async def test_a_tool_is_listed_and_callable_exactly_when_its_scope_is_held(spec, held, bearer, mcp_session):
    bearer(principal(scopes=frozenset({held} if held else set())))
    holds_it = held == spec.scope

    async with mcp_session(auth()) as session:
        listed = {tool.name for tool in (await session.list_tools()).tools}
        result = await session.call_tool(spec.name, _arguments(spec))

    assert (spec.name in listed) is holds_it, spec.name
    if holds_it:
        # Handlers are **not** stubbed: the call really reaches one, which is
        # what proves the listed name is dispatchable. Without a database it
        # will usually fail on its own — fine, as long as it did not fail on
        # the scope.
        if result.isError:
            assert error_payload(result)["code"] != 26302
    else:
        payload = error_payload(result)
        assert payload["code"] == 26302
        assert payload["data"]["required"] == spec.scope


def test_every_registry_entry_is_covered_by_this_matrix():
    """A tool added without a case here fails now, not in production."""

    assert len(CASES) == len(AVAILABLE) * len(KEYS)
    assert {spec.name for spec, _ in CASES} == {spec.name for spec in AVAILABLE}


def test_each_tool_maps_to_exactly_one_scope_from_the_published_table():
    """DEV-01 ①: four scopes, six categories, no tool outside the mapping."""

    assert {spec.scope for spec in registry.TOOL_REGISTRY} == set(SCOPES)
    for spec in registry.TOOL_REGISTRY:
        assert spec.name.startswith("bisheng_"), spec.name


def test_tools_whose_dependency_has_not_landed_are_absent_rather_than_broken():
    """Absent is the honest answer; present-but-failing sends an agent in circles."""

    unavailable = [spec.name for spec in registry.TOOL_REGISTRY if not spec.available()]
    for name in unavailable:
        assert name not in {spec.name for spec in AVAILABLE}


def _arguments(spec) -> dict:
    """Minimal valid-looking arguments; admission is decided before they are read."""

    return {
        "bisheng_knowledge_search": {"query": "x"},
        "bisheng_identity_get_user": {"user_id": 1},
        "bisheng_dept_members": {"dept_id": "BS@a1"},
        "bisheng_app_status": {"app_id": "app-1"},
        "bisheng_app_logs": {"app_id": "app-1"},
        "bisheng_app_db_tables": {"app_id": "app-1"},
        "bisheng_app_db_schema": {"app_id": "app-1", "table": "t"},
        "bisheng_app_db_rows": {"app_id": "app-1", "table": "t"},
        "bisheng_app_db_row_update": {"app_id": "app-1", "table": "t", "key": "1", "values": {"a": 1}},
    }.get(spec.name, {})
