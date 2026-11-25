from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from bisheng.common.errcode.dsh import (
    DshModelNotAllowedError,
    DshMonthlyTokenLimitExceededError,
    DshUserDisabledError,
)
from bisheng.common.services.config_service import settings
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.dsh.domain.schemas.pricing import CreditSettingState
from test.dsh.pricing_fixtures import LEGACY_EQUIVALENT_PRICING
from bisheng.dsh.domain.services import chat_credits
from bisheng.dsh.infrastructure.quota_redis import QuotaRejected
from bisheng.linsight.domain.task_exec import LinsightWorkflowTask
from bisheng.worker.workflow.redis_callback import RedisCallback


def test_governed_covers_app_types_and_honors_switch_and_unbilled(monkeypatch):
    monkeypatch.setattr(settings.credit_billing, "enabled", True)

    for app_type in (
        ApplicationTypeEnum.DAILY_CHAT,
        ApplicationTypeEnum.LINSIGHT,
        ApplicationTypeEnum.KNOWLEDGE_SPACE,
        ApplicationTypeEnum.ASSISTANT,
        ApplicationTypeEnum.WORKFLOW,
        ApplicationTypeEnum.MODEL_GATEWAY,
    ):
        assert chat_credits.governed(SimpleNamespace(app_type=app_type)) is True

    assert chat_credits.governed(SimpleNamespace(app_type=ApplicationTypeEnum.EVALUATION)) is False

    with chat_credits.billing_context(open_api_unbilled=True):
        assert chat_credits.governed(SimpleNamespace(app_type=ApplicationTypeEnum.ASSISTANT)) is False
        assert chat_credits.governed(SimpleNamespace(app_type=ApplicationTypeEnum.WORKFLOW)) is False
        assert chat_credits.governed(SimpleNamespace(app_type=ApplicationTypeEnum.LINSIGHT)) is False

    monkeypatch.setattr(settings.credit_billing, "enabled", False)
    assert chat_credits.governed(SimpleNamespace(app_type=ApplicationTypeEnum.ASSISTANT)) is False


async def test_start_records_source_metadata_and_admin_selected_and_tenant_isolation(monkeypatch):
    monkeypatch.setattr(settings.credit_billing, "enabled", True)
    captured_events = []

    async def fake_check_and_start(event, *, monthly_token_limit, mode=""):
        captured_events.append((event, monthly_token_limit, mode))
        return event

    service = SimpleNamespace(
        model=object(),
        activate=AsyncMock(),
        usage=SimpleNamespace(check_and_start=fake_check_and_start),
    )

    monkeypatch.setattr(
        "bisheng.dsh.domain.repositories.identities.CurrentIdentityRecords.get",
        AsyncMock(
            return_value=SimpleNamespace(active=True, tenant_active=True, natural_person=True),
        ),
    )
    monkeypatch.setattr(
        "bisheng.dsh.runtime.read_policy",
        AsyncMock(
            return_value=SimpleNamespace(
                monthly_token_limit=5000,
                version=1,
                quota_epoch=1,
                allowed_model_ids=(),
            )
        ),
    )
    monkeypatch.setattr(
        "bisheng.dsh.runtime.read_model_pricing",
        AsyncMock(return_value=dict(LEGACY_EQUIVALENT_PRICING)),
    )
    monkeypatch.setattr(
        "bisheng.dsh.runtime.read_credit_setting",
        AsyncMock(return_value=CreditSettingState(version=1)),
    )
    monkeypatch.setattr("bisheng.dsh.runtime.get_model_runtime", AsyncMock(return_value=service))

    model = SimpleNamespace(
        user_id=101,
        model_info=SimpleNamespace(id=7),
        app_type=ApplicationTypeEnum.ASSISTANT,
        app_id="asst-42",
        admin_selected=False,
    )

    token = set_current_tenant_id(1)
    try:
        with pytest.raises(DshModelNotAllowedError):
            await chat_credits.start(model)

        model.admin_selected = True
        with chat_credits.billing_context(source_type="assistant", source_id="asst-42"):
            await chat_credits.start(model)

        assert len(captured_events) == 1
        event = captured_events[0][0]
        assert event.source_type == "assistant"
        assert event.source_id == "asst-42"

        # 额度用完必须抛出 26121
        service.usage.check_and_start = AsyncMock(side_effect=QuotaRejected("quota_exceeded"))
        with pytest.raises(DshMonthlyTokenLimitExceededError):
            await chat_credits.start(model)

        # 跨租户人员在 UserTenant 中查不到本租户有效成员，积分层不得兜底放行
        monkeypatch.setattr(
            "bisheng.dsh.domain.repositories.identities.CurrentIdentityRecords.get",
            AsyncMock(return_value=None),
        )
        with pytest.raises(DshUserDisabledError):
            await chat_credits.start(model)
    finally:
        current_tenant_id.reset(token)


async def test_assistant_and_workflow_pass_admin_selected_true(monkeypatch):
    from bisheng.api.services.assistant_agent import AssistantAgent
    from bisheng.workflow.nodes.agent.agent import AgentNode
    from bisheng.workflow.nodes.input.input import InputNode
    from bisheng.workflow.nodes.llm.llm import LLMNode
    from bisheng.workflow.nodes.rag.rag import RagNode

    async_calls = []

    async def fake_async_llm(**kwargs):
        async_calls.append(kwargs)
        return MagicMock()

    monkeypatch.setattr("bisheng.llm.domain.services.llm.LLMService.get_bisheng_llm", fake_async_llm)
    llm_entry = SimpleNamespace(
        model_id=11,
        streaming=True,
        default=True,
        agent_executor_type="function",
        knowledge_max_content=1000,
        knowledge_sort_index=False,
    )
    monkeypatch.setattr(
        "bisheng.llm.domain.services.llm.LLMService.aget_assistant_llm_with_meta",
        AsyncMock(return_value=(SimpleNamespace(llm_list=[llm_entry]), None, None)),
    )
    monkeypatch.setattr(
        "bisheng.llm.domain.services.llm.LLMService.get_assistant_llm",
        AsyncMock(
            return_value=SimpleNamespace(
                llm_list=[llm_entry],
                auto_llm=SimpleNamespace(model_id=12, streaming=False),
            )
        ),
    )

    agent = object.__new__(AssistantAgent)
    agent.assistant = SimpleNamespace(id="asst-1", name="demo", model_name="11", temperature=0.5)
    agent.login_user = SimpleNamespace(user_id=10, tenant_id=1)
    agent.reference_session = SimpleNamespace(source_tenant_id=1)
    agent.invoke_user_id = 10
    await agent.init_llm()
    await agent.init_auto_update_llm()

    assert len(async_calls) == 2
    assert all(call.get("admin_selected") is True for call in async_calls)

    sync_calls = []

    def fake_sync_llm(**kwargs):
        sync_calls.append(kwargs)
        return MagicMock(invoke=MagicMock(return_value=SimpleNamespace(content="[]")))

    monkeypatch.setattr("bisheng.llm.domain.services.llm.LLMService.get_bisheng_llm_sync", fake_sync_llm)
    monkeypatch.setattr("bisheng.workflow.nodes.rag.rag.get_minio_storage_sync", lambda: MagicMock())

    base_state = {
        "id": "node-1",
        "name": "n1",
        "type": "llm",
        "v": "1",
        "group_params": [],
    }

    llm_node = object.__new__(LLMNode)
    llm_node.workflow_id = "wf-1"
    llm_node.workflow_name = "wf"
    llm_node.user_id = 10
    llm_node.id = "node-llm"
    llm_node.name = "llm"
    llm_node.graph_state = MagicMock()
    llm_node.node_data = SimpleNamespace(tab={"value": "single"})
    llm_node.node_params = {
        "model_id": 21,
        "temperature": 0.7,
        "tab_value": "single",
        "system_prompt": "",
        "user_prompt": "hi",
        "output_user": False,
    }
    with patch("bisheng.workflow.nodes.base.BaseNode.__init__", return_value=None):
        LLMNode.__init__(llm_node, base_state, "wf-1", "wf", 10, MagicMock(), MagicMock(), 10)

    rag_node = object.__new__(RagNode)
    rag_node.workflow_id = "wf-1"
    rag_node.workflow_name = "wf"
    rag_node.user_id = 10
    rag_node.id = "node-rag"
    rag_node.name = "rag"
    rag_node.graph_state = MagicMock()
    rag_node.node_params = {
        "model_id": 22,
        "temperature": 0.7,
        "system_prompt": "",
        "user_prompt": "hi",
        "knowledge": {"value": []},
        "user_auth": False,
        "max_chunk_size": 500,
    }
    with patch("bisheng.workflow.nodes.base.BaseNode.__init__", return_value=None):
        RagNode.__init__(rag_node, base_state, "wf-1", "wf", 10, MagicMock(), MagicMock(), 10)

    agent_node = object.__new__(AgentNode)
    agent_node.workflow_id = "wf-1"
    agent_node.workflow_name = "wf"
    agent_node.user_id = 10
    agent_node.id = "node-agent"
    agent_node.name = "agent"
    agent_node.graph_state = MagicMock()
    agent_node.node_data = SimpleNamespace(tab={"value": "single"})
    agent_node.node_params = {
        "model_id": 23,
        "temperature": 0.5,
        "system_prompt": "",
        "user_prompt": "hi",
        "chat_history_flag": {"value": 0},
        "output_user": False,
        "tool_list": [],
        "knowledge_id": {"type": "kb", "value": []},
        "user_auth": False,
        "sql_agent": {"open": False},
    }
    with patch("bisheng.workflow.nodes.base.BaseNode.__init__", return_value=None):
        AgentNode.__init__(agent_node, base_state, "wf-1", "wf", 10, MagicMock(), MagicMock(), 10)

    input_node = object.__new__(InputNode)
    input_node.workflow_id = "wf-1"
    input_node.workflow_name = "wf"
    input_node.user_id = 10
    input_node.id = "node-input"
    input_node.name = "input"
    input_node.graph_state = SimpleNamespace(get_history_memory=lambda n: "hello")
    input_node.parse_msg_with_variables = lambda prompt: (prompt, [])
    input_node.node_params = {}
    input_node._original_node_params = {
        "recommended_questions_flag": True,
        "recommended_llm": 24,
        "recommended_system_prompt": "prompt",
        "recommended_history_num": 3,
    }
    with patch("bisheng.llm.domain.services.llm.LLMService.get_bisheng_llm_sync", side_effect=fake_sync_llm):
        fake_sync_llm_prev = len(sync_calls)
        input_node.handle_recommended_questions()
        assert len(sync_calls) == fake_sync_llm_prev + 1

    assert len(sync_calls) == 4
    assert all(call.get("admin_selected") is True for call in sync_calls)


def test_workflow_credit_exhausted_preserves_26121_in_callback(monkeypatch):
    from bisheng.workflow.graph.graph_engine import GraphEngine

    cb = object.__new__(RedisCallback)
    cb.workflow_id = "wf-1"
    cb.chat_id = "chat-1"
    cb.user_id = 10

    engine = object.__new__(GraphEngine)
    engine.graph_config = {}
    engine.callback = MagicMock()
    engine.graph = SimpleNamespace(stream=MagicMock(side_effect=DshMonthlyTokenLimitExceededError()))
    engine._run({"flag": True})

    assert engine.status == "FAILED"
    resp = cb.parse_workflow_failed({"status": engine.status, "reason": engine.reason})
    assert resp is not None
    assert resp.message["status_code"] == 26121


async def test_linsight_resume_no_reprobe_and_open_api_channel_unbilled(monkeypatch):
    monkeypatch.setattr(settings.credit_billing, "enabled", True)
    executor = object.__new__(LinsightWorkflowTask)
    executor.session_version_id = "sv-1"
    executor.file_dir = "/tmp/linsight-test"
    executor._update_session_status = AsyncMock()
    executor._begin_memory_round = AsyncMock()
    executor._sync_workspace_originals = AsyncMock()
    executor._provision_session_skills = AsyncMock()
    executor._generate_tools = AsyncMock(return_value=[])
    executor._resolve_allowed_knowledge_ids = AsyncMock(return_value=None)
    executor._create_agent = AsyncMock(return_value=MagicMock())
    executor._check_termination = MagicMock()
    executor._handle_task_completion = AsyncMock()
    executor._get_llm = AsyncMock(return_value=SimpleNamespace(app_type=ApplicationTypeEnum.LINSIGHT))

    monkeypatch.setattr("bisheng.linsight.domain.services.checkpointer.make_checkpointer", lambda: None)
    monkeypatch.setattr("bisheng.linsight.domain.task_exec.ToolServices.init_linsight_tools", AsyncMock(return_value=[]))

    admit_calls = []

    async def fake_admit_round(llm):
        admit_calls.append(llm)

    monkeypatch.setattr(chat_credits, "admit_round", fake_admit_round)

    # Normal resume must NOT re-probe via admit_round, and must run unmetered
    seen_resume_flags = []

    async def fake_drive_resume(agent, session_model, user_input):
        seen_resume_flags.append((chat_credits._round_admitted.get(), chat_credits.is_open_api_unbilled()))

    executor._drive_resume = fake_drive_resume
    executor._finalize_resumed_answer = AsyncMock()
    executor._state_manager = SimpleNamespace(restamp_clarify_answers=AsyncMock())

    normal_session = SimpleNamespace(id="sv-1", status="IN_PROGRESS", api_meta={})
    await executor._resume_workflow(normal_session, {"answer": "go"})
    assert admit_calls == []
    assert seen_resume_flags == [(True, False)]

    # Open API Linsight: execute / continue / resume all run with open_api_unbilled=True and skip admit_round quota deduction
    seen_open_flags = []

    async def fake_execute_tasks(agent, session_model):
        seen_open_flags.append(("execute", chat_credits.is_open_api_unbilled()))
        return True

    async def fake_drive_continue(agent, session_model, question):
        seen_open_flags.append(("continue", chat_credits.is_open_api_unbilled()))

    async def fake_drive_resume_open(agent, session_model, user_input):
        seen_open_flags.append(("resume", chat_credits.is_open_api_unbilled()))

    executor._execute_agent_tasks = fake_execute_tasks
    executor._drive_continue = fake_drive_continue
    executor._drive_resume = fake_drive_resume_open
    executor._seed_workspace_from_previous = AsyncMock()
    monkeypatch.setattr(
        "bisheng.linsight.domain.task_exec.linsight_execute_utils.persist_task_turn_message",
        AsyncMock(),
    )

    open_session = SimpleNamespace(id="sv-2", status="IN_PROGRESS", api_meta={"channel": "open_api_v2"})
    await executor._execute_workflow(open_session)
    await executor._continue_workflow(open_session, "next")
    await executor._resume_workflow(open_session, {"answer": "go"})

    assert seen_open_flags == [
        ("execute", True),
        ("continue", True),
        ("resume", True),
    ]
