"""F132 T062: workflow memory switch, publish check and runtime switch source.

Covers AC-70, AC-71, AC-80, AC-85. The runtime switch comes from the ONLINE
version in the database (R5, decision 17), never from the graph the client sent.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.errcode.memory import MemorySearchLimitInvalidError, MemoryWorkflowSwitchOffError
from bisheng.memory.domain.ports import MemoryContext
from bisheng.memory.domain.services.app_switch import start_node_memory_enabled, workflow_memory_enabled_sync
from bisheng.workflow.callback.base_callback import BaseCallback
from bisheng.workflow.graph.graph_engine import GraphEngine
from bisheng.workflow.graph.workflow import Workflow
from test.workflow.memory_fixtures import (  # noqa: F401  (fixtures)
    TENANT_A,
    USER_1,
    details,
    graph,
    import_worker_tasks,
    index,
    kv,
    memory_db,
    memory_runtime_config,
    register_chat,
    retriever_node,
    seed_online_workflow,
    service,
    wired,
)

CHAT = "wf-chat-1"


# ---- AC-70 default off ------------------------------------------------------------------


def test_ac70_new_and_legacy_start_nodes_are_off():
    """AC-70, AC-71: no ``memory_enabled`` param (new default or an old version) means off."""
    assert start_node_memory_enabled(graph()) is False
    assert start_node_memory_enabled(graph(memory_enabled=False)) is False
    assert start_node_memory_enabled(graph(memory_enabled=True)) is True


def test_ac70_engine_and_workflow_default_to_off():
    """AC-70: an engine built without the run values has an empty chat_id and the switch off."""
    engine = GraphEngine(
        workflow_id="wf-1", workflow_data=graph(memory_enabled=True), max_steps=10, callback=BaseCallback()
    )
    assert (engine.graph_state.chat_id, engine.graph_state.memory_enabled) == ("", False)
    wf = Workflow("wf-1", "x", None, graph(memory_enabled=True), False, 10, 10, BaseCallback())
    assert wf.graph_engine.graph_state.memory_enabled is False


def test_ac71_engine_carries_run_values_read_only():
    """AC-71 / R5: Workflow -> GraphEngine -> GraphState carries chat_id and the switch, frozen."""
    wf = Workflow("wf-1", "x", None, graph(), False, 10, 10, BaseCallback(), chat_id=CHAT, memory_enabled=True)
    state = wf.graph_engine.graph_state
    assert (state.chat_id, state.memory_enabled) == (CHAT, True)
    with pytest.raises(ValueError):
        state.memory_enabled = False


# ---- AC-71 switch lives in the version, online version decides ----------------------------


def test_ac71_switch_read_from_online_current_version(memory_db):
    """AC-71: the switch follows the version; only the current version of an ONLINE flow counts."""
    seed_online_workflow(memory_db, "on", switch=True, extra_versions=[graph(memory_enabled=False)])
    seed_online_workflow(memory_db, "draft-on", switch=False, extra_versions=[graph(memory_enabled=True)])
    seed_online_workflow(memory_db, "legacy", switch=None)
    seed_online_workflow(memory_db, "offline", switch=True, status=1)
    assert workflow_memory_enabled_sync("on") is True
    assert workflow_memory_enabled_sync("draft-on") is False
    assert workflow_memory_enabled_sync("legacy") is False
    assert workflow_memory_enabled_sync("offline") is False


async def test_ac70_only_editors_can_save_the_switch(monkeypatch):
    """AC-70: the switch is saved with the version data; saving needs edit permission on the workflow."""
    from bisheng.api.services import flow as flow_service
    from bisheng.api.services.flow import FlowService

    version = SimpleNamespace(
        flow_id="wf-1", is_current=0, name="v", description="", data=graph(memory_enabled=False), is_delete=0
    )
    saved = AsyncMock(side_effect=lambda v: v)
    monkeypatch.setattr(flow_service.telemetry_service, "log_event", AsyncMock())
    monkeypatch.setattr(flow_service.FlowVersionDao, "aget_version_by_id", AsyncMock(return_value=version))
    monkeypatch.setattr(flow_service.FlowVersionDao, "aupdate_version", saved)
    monkeypatch.setattr(FlowService, "update_flow_hook", AsyncMock())
    # Kunlian (F118): an ordinary, non-registered workflow
    monkeypatch.setattr(
        "bisheng.workflow.application.kunlian_workflow_management.workflow_scope", lambda *a, **k: None
    )
    body = SimpleNamespace(name=None, description=None, data=graph(memory_enabled=True))

    monkeypatch.setattr(FlowService, "judge_flow_write_permission", AsyncMock(side_effect=UnAuthorizedError()))
    with pytest.raises(UnAuthorizedError):
        await FlowService.update_version_info(Mock(), SimpleNamespace(user_id=2), 7, body)
    saved.assert_not_awaited()

    monkeypatch.setattr(FlowService, "judge_flow_write_permission", AsyncMock(return_value=SimpleNamespace(status=1, tenant_id=1, id="wf-1", data={"nodes": []})))
    await FlowService.update_version_info(Mock(), SimpleNamespace(user_id=1), 7, body)
    assert start_node_memory_enabled(saved.await_args.args[0].data) is True


# ---- AC-85 / AC-80 publish check ----------------------------------------------------------


@pytest.fixture
def publish(monkeypatch):
    from bisheng.api.services import workflow as wf_service
    from bisheng.api.services.workflow import WorkFlowService

    state = SimpleNamespace(data=None, change=AsyncMock(), update=AsyncMock())

    async def _version(version_id):
        return SimpleNamespace(id=version_id, flow_id="wf-1", data=state.data)

    monkeypatch.setattr(
        wf_service.FlowDao, "aget_flow_by_id", AsyncMock(return_value=SimpleNamespace(name="报销流程", status=1, tenant_id=1, data={"nodes": []}))
    )
    monkeypatch.setattr(wf_service, "require_business_action", AsyncMock())
    monkeypatch.setattr(
        "bisheng.workflow.application.kunlian_workflow_management.workflow_scope", lambda *a, **k: None
    )
    monkeypatch.setattr(wf_service.FlowVersionDao, "aget_version_by_id", _version)
    monkeypatch.setattr(wf_service.FlowVersionDao, "change_current_version", state.change)
    monkeypatch.setattr(wf_service.FlowDao, "aupdate_flow", state.update)
    monkeypatch.setattr(wf_service.telemetry_service, "log_event", AsyncMock())

    async def _go(data, status=2):
        state.data = data
        await WorkFlowService.update_flow_status(SimpleNamespace(user_id=1), "wf-1", 3, status)

    state.go = _go
    return state


async def test_ac85_retriever_with_switch_off_is_refused(publish):
    """AC-85: a retriever node with the start-node switch off (or missing) cannot go online (12109)."""
    for switch in (False, None):
        with pytest.raises(MemoryWorkflowSwitchOffError) as exc:
            await publish.go(graph(retriever_node(query="出差"), memory_enabled=switch))
        assert exc.value.code == 12109
    publish.change.assert_not_awaited()


async def test_ac85_switch_on_goes_online(publish):
    """AC-85: with the switch on the same graph goes online."""
    await publish.go(graph(retriever_node(query="出差"), retriever_node("mr_2", query="报销"), memory_enabled=True))
    publish.change.assert_awaited_once()


@pytest.mark.parametrize("limit", [0, 101, 2.5, "abc"])
async def test_ac80_invalid_limit_is_refused_at_publish(publish, limit):
    """AC-80: an invalid node limit is refused at publish with 12108."""
    with pytest.raises(MemorySearchLimitInvalidError) as exc:
        await publish.go(graph(retriever_node(query="出差", limit=limit), memory_enabled=True))
    assert exc.value.code == 12108
    publish.change.assert_not_awaited()


async def test_publish_without_retriever_ignores_switch_and_offline_skips_check(publish):
    """AC-85: graphs without a retriever node are unaffected; going offline does not validate."""
    await publish.go(graph(memory_enabled=False))
    await publish.go(graph(retriever_node(query="出差"), memory_enabled=False), status=1)
    publish.change.assert_awaited_once()


# ---- runtime: the switch comes from the database, not the client graph ---------------------


class FakeRedisCallback(BaseCallback):
    graph_data: dict = {}

    def __init__(self, unique_id, workflow_id, chat_id, user_id, source="platform", tenant_id=None):
        self.unique_id, self.workflow_id, self.chat_id, self.user_id = unique_id, workflow_id, chat_id, user_id
        self.statuses = []
        self.workflow = None

    def set_workflow_status(self, status, reason=""):
        self.statuses.append(status)

    def get_workflow_data(self):
        return FakeRedisCallback.graph_data


@pytest.fixture
def worker(monkeypatch):
    tasks = import_worker_tasks()
    monkeypatch.setattr(tasks, "RedisCallback", FakeRedisCallback)
    # The start node looks up the running user's profile; runs here use the chat owner's id.
    from bisheng.workflow.nodes.start import start as start_mod

    monkeypatch.setattr(start_mod.UserDao, "get_user", Mock(return_value=SimpleNamespace(user_name="u101")))
    monkeypatch.setattr(start_mod.UserGroupDao, "get_user_group", Mock(return_value=[]))
    monkeypatch.setattr(start_mod.UserRoleDao, "get_user_roles", Mock(return_value=[]))
    monkeypatch.setattr(start_mod.UserDepartmentDao, "get_user_primary_department", Mock(return_value=None))
    monkeypatch.setattr(
        tasks.FlowDao, "get_flow_by_id", Mock(return_value=SimpleNamespace(name="报销流程", tenant_id=1, user_id=1))
    )
    monkeypatch.setattr(
        type(tasks.settings),
        "get_workflow_conf",
        lambda self: SimpleNamespace(max_steps=10, timeout=10),
        raising=False,
    )
    built = []
    real = tasks.Workflow

    def _capture(*args, **kwargs):
        wf = real(*args, **kwargs)
        built.append(wf)
        return wf

    monkeypatch.setattr(tasks, "Workflow", _capture)
    return SimpleNamespace(tasks=tasks, built=built)


def _ctx():
    return MemoryContext(tenant_id=TENANT_A, user_id=USER_1, chat_id="src", turn_id="t")


@pytest.mark.parametrize(("db_switch", "expected"), [(False, False), (True, True)])
async def test_ac71_runtime_switch_from_online_version_not_client_graph(memory_db, wired, worker, db_switch, expected):
    """AC-71 / decision 17: the client sends a graph with the switch on; the database decides."""
    seed_online_workflow(memory_db, "wf-1", switch=db_switch)
    register_chat(memory_db, CHAT)
    await wired.service.write(_ctx(), "remember", content="用户的成本中心是 C-100", type="fact")
    FakeRedisCallback.graph_data = graph(retriever_node(query="成本中心"), memory_enabled=True)

    await asyncio.to_thread(worker.tasks._execute_workflow, "u-1", "wf-1", CHAT, USER_1)

    state = worker.built[-1].graph_engine.graph_state
    assert (state.chat_id, state.memory_enabled) == (CHAT, expected)
    out = state.get_variable("memory_retriever_1", "retrieved_memory")
    assert (len(out) == 1) is expected


async def test_no_chat_id_run_does_not_read_the_switch(memory_db, wired, worker, monkeypatch):
    """AC-83 / AC-10: evaluation and debug runs (empty chat_id) skip the lookup and stay off."""
    lookup = Mock(return_value=True)
    monkeypatch.setattr(worker.tasks, "workflow_memory_enabled_sync", lookup)
    FakeRedisCallback.graph_data = graph(retriever_node(query="成本中心"), memory_enabled=True)
    await asyncio.to_thread(worker.tasks._execute_workflow, "u-2", "wf-1", "", 0)
    state = worker.built[-1].graph_engine.graph_state
    assert (state.chat_id, state.memory_enabled) == ("", False)
    lookup.assert_not_called()


async def test_ac10_open_api_run_with_registered_chat_gets_no_memory(memory_db, wired, worker):
    """AC-10: an open-API run (source="api") reusing a registered chat_id never reads memory."""
    seed_online_workflow(memory_db, "wf-1", switch=True)
    register_chat(memory_db, CHAT)
    await wired.service.write(_ctx(), "remember", content="用户的成本中心是 C-100", type="fact")
    FakeRedisCallback.graph_data = graph(retriever_node(query="成本中心"), memory_enabled=True)

    await asyncio.to_thread(worker.tasks._execute_workflow, "u-3", "wf-1", CHAT, USER_1, "api")

    state = worker.built[-1].graph_engine.graph_state
    assert state.memory_enabled is False
    assert state.get_variable("memory_retriever_1", "retrieved_memory") == []
