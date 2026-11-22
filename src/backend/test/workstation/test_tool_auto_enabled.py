"""F005: a workbench tool an admin auto-enables is hidden from users and added to every workbench send.

Covers the config field (mutually exclusive with ``default_checked``), its survival
through the child-tenant projection, the send-time injection and the personal
opt-out exemption.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from bisheng.api.v1.schemas import ToolConfig
from bisheng.core.context.tenant import bypass_tenant_filter, set_current_tenant_id
from bisheng.tool.domain.models.gpts_tools import GptsTools, GptsToolsType
from bisheng.workstation.domain.schemas.chat import APIChatCompletion, ToolPayload
from bisheng.workstation.domain.services import workstation_service as ws_module
from bisheng.workstation.domain.services.workstation_service import WorkStationService

pytestmark = pytest.mark.real_auto_enabled

ROOT, CHILD = 1, 2


def test_auto_enabled_clears_default_checked():
    tool = ToolConfig(id=1, name="代码执行器", default_checked=True, auto_enabled=True)

    assert (tool.auto_enabled, tool.default_checked) == (True, False)


def test_a_config_without_the_field_reads_as_user_picked():
    tool = ToolConfig.model_validate({"id": 1, "name": "联网搜索", "default_checked": True})

    assert (tool.auto_enabled, tool.default_checked) == (False, True)


def test_keys_come_only_from_auto_enabled_groups():
    payload = (
        '{"tools": ['
        '{"id": 1, "auto_enabled": true, "children": [{"id": 11, "tool_key": "bisheng_code_interpreter"}]},'
        '{"id": 2, "default_checked": true, "children": [{"id": 21, "tool_key": "web_search"}]}'
        "]}"
    )

    assert WorkStationService._auto_enabled_tool_keys_from(payload) == {"bisheng_code_interpreter"}
    assert WorkStationService._auto_enabled_tool_keys_from(None) == set()
    assert WorkStationService._auto_enabled_tool_keys_from("not json") == set()


@pytest.fixture
async def db(monkeypatch):
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import StaticPool
    from sqlmodel.ext.asyncio.session import AsyncSession

    from bisheng.core.database import tenant_filter

    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(GptsToolsType.__table__.create)
        await conn.run_sync(GptsTools.__table__.create)

    @asynccontextmanager
    async def _session():
        session = AsyncSession(bind=engine, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()

    monkeypatch.setattr(ws_module, "get_async_db_session", _session)
    tenant_filter._initialized = False
    tenant_filter._tenant_aware_tables = set()
    tenant_filter.register_tenant_filter_events()

    async with _session() as session:
        with bypass_tenant_filter():
            for tenant, type_id, tool_id in ((ROOT, 1, 11), (CHILD, 2, 22)):
                session.add(GptsToolsType(id=type_id, name="代码执行器", tenant_id=tenant, is_preset=1))
                session.add(
                    GptsTools(
                        id=tool_id,
                        name="代码执行器",
                        tool_key="bisheng_code_interpreter",
                        type=type_id,
                        tenant_id=tenant,
                        is_preset=1,
                    )
                )
            await session.commit()
    yield
    set_current_tenant_id(ROOT)


async def test_child_tenant_projection_keeps_auto_enabled(db):
    set_current_tenant_id(CHILD)
    stored = [{"id": 1, "auto_enabled": True, "children": [{"id": 11, "tool_key": "bisheng_code_interpreter"}]}]

    projected = await WorkStationService._aproject_tools_for_current_tenant(stored, ROOT)

    assert [(group["id"], group["auto_enabled"], group["default_checked"]) for group in projected] == [(2, True, False)]
    assert projected[0]["children"][0]["id"] == 22


async def test_auto_enabled_ids_resolve_in_the_current_tenant(db, monkeypatch):
    set_current_tenant_id(CHILD)
    payload = (
        '{"tools": [{"id": 1, "auto_enabled": true, "children": [{"id": 11, "tool_key": "bisheng_code_interpreter"}]}]}'
    )

    async def _resolve(cls, key):
        return payload, True, ROOT, True

    monkeypatch.setattr(WorkStationService, "_aresolve_tenant_config", classmethod(_resolve))

    assert await WorkStationService.aauto_enabled_tool_ids() == {22}


# -- send-time injection ----------------------------------------------------


def _config(*groups: ToolConfig):
    return SimpleNamespace(tools=list(groups))


@pytest.fixture
def user():
    return SimpleNamespace(user_id=7)


@pytest.fixture
def allow_all(monkeypatch):
    async def _batch(user, *, resource_type, resource_ids, actions):
        return {str(rid): frozenset({"use"}) for rid in resource_ids}

    monkeypatch.setattr("bisheng.permission.application.business_authorization.batch_check_business_actions", _batch)


def _patch_config(monkeypatch, config):
    async def _get(cls, *, for_picker=False):
        return config

    monkeypatch.setattr(WorkStationService, "get_daily_chat_config", classmethod(_get))


CODE = ToolConfig(
    id=2, name="代码执行器", auto_enabled=True, children=[{"id": 22, "tool_key": "bisheng_code_interpreter"}]
)
WEB = ToolConfig(id=3, name="联网搜索", default_checked=True, children=[{"id": 33, "tool_key": "web_search"}])


async def test_auto_enabled_tools_are_added_to_the_request(monkeypatch, user, allow_all):
    _patch_config(monkeypatch, _config(CODE, WEB))
    data = APIChatCompletion(
        model="m", clientTimestamp="2026-11-20T00:00:00Z", text="hi", tools=[ToolPayload(id=33, tool_key="web_search")]
    )

    out = await WorkStationService.awith_auto_enabled_tools(data, user)

    assert [(tool.id, tool.tool_key) for tool in out.tools] == [(33, "web_search"), (22, "bisheng_code_interpreter")]


async def test_projected_config_groups_are_plain_dicts(monkeypatch, user, allow_all):
    """The child-tenant projection hands the groups back as dicts (found on 114)."""
    _patch_config(monkeypatch, _config(CODE.model_dump(mode="json"), WEB.model_dump(mode="json")))
    data = APIChatCompletion(model="m", clientTimestamp="2026-11-20T00:00:00Z", text="hi")

    out = await WorkStationService.awith_auto_enabled_tools(data, user)

    assert [(tool.id, tool.tool_key) for tool in out.tools] == [(22, "bisheng_code_interpreter")]


async def test_a_tool_already_in_the_request_is_not_added_twice(monkeypatch, user, allow_all):
    _patch_config(monkeypatch, _config(CODE))
    data = APIChatCompletion(
        model="m",
        clientTimestamp="2026-11-20T00:00:00Z",
        text="hi",
        tools=[ToolPayload(id=22, tool_key="bisheng_code_interpreter")],
    )

    out = await WorkStationService.awith_auto_enabled_tools(data, user)

    assert [tool.id for tool in out.tools] == [22]


async def test_a_user_without_use_permission_gets_nothing_added(monkeypatch, user):
    async def _deny(user, *, resource_type, resource_ids, actions):
        return {}

    monkeypatch.setattr("bisheng.permission.application.business_authorization.batch_check_business_actions", _deny)
    _patch_config(monkeypatch, _config(CODE))
    data = APIChatCompletion(model="m", clientTimestamp="2026-11-20T00:00:00Z", text="hi")

    out = await WorkStationService.awith_auto_enabled_tools(data, user)

    assert not out.tools


async def test_nothing_auto_enabled_leaves_the_request_unchanged(monkeypatch, user):
    async def _fail(*args, **kwargs):
        raise AssertionError("no permission check without auto-enabled tools")

    monkeypatch.setattr("bisheng.permission.application.business_authorization.batch_check_business_actions", _fail)
    _patch_config(monkeypatch, _config(WEB))
    data = APIChatCompletion(model="m", clientTimestamp="2026-11-20T00:00:00Z", text="hi")

    assert await WorkStationService.awith_auto_enabled_tools(data, user) is data


def test_only_the_login_state_entry_injects():
    import inspect

    from bisheng.open_endpoints.api.endpoints import workstation as open_workstation
    from bisheng.workstation.api.endpoints import chat as login_chat

    assert "awith_auto_enabled_tools" in inspect.getsource(login_chat.chat_completions)
    assert "awith_auto_enabled_tools" not in inspect.getsource(open_workstation)


# -- personal opt-out exemption ----------------------------------------------


class _Repo:
    def __init__(self, disabled: set[int]):
        self.disabled = disabled

    async def disabled_ids(self, user_id):
        return set(self.disabled)

    def enabled_sync(self, user_id, tool_id):
        return tool_id not in self.disabled


async def test_a_personal_opt_out_does_not_stop_an_auto_enabled_tool(monkeypatch):
    from bisheng.tool.domain.services.user_availability import UserToolAvailabilityService

    async def _ids(cls):
        return {22}

    monkeypatch.setattr(WorkStationService, "aauto_enabled_tool_ids", classmethod(_ids))
    monkeypatch.setattr(WorkStationService, "auto_enabled_tool_ids", classmethod(lambda cls: {22}))
    service = UserToolAvailabilityService(7, repository=_Repo({22, 33}))
    tools = [SimpleNamespace(id=22, is_preset=1), SimpleNamespace(id=33, is_preset=1)]

    assert await service.disabled_ids(tools) == {33}
    await service.ensure_enabled(22)
    service.ensure_enabled_sync(22)
    with pytest.raises(PermissionError):
        service.ensure_enabled_sync(33)


async def test_no_opt_out_on_record_skips_the_config_read(monkeypatch):
    from bisheng.tool.domain.services.user_availability import UserToolAvailabilityService

    async def _fail(cls):
        raise AssertionError("the config must not be read without an opt-out")

    monkeypatch.setattr(WorkStationService, "aauto_enabled_tool_ids", classmethod(_fail))
    service = UserToolAvailabilityService(7, repository=_Repo(set()))

    assert await service.disabled_ids([SimpleNamespace(id=22, is_preset=1)]) == set()
