"""F078 T26: skills in the workflow agent node."""

from types import SimpleNamespace

import pytest
from langchain_classic.memory import ConversationBufferWindowMemory
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

import bisheng.workflow.nodes.agent.agent as agent_module
import bisheng.workflow.nodes.agent.skill_support as support
from bisheng.agent_runtime.domain.services.agent_runner import RunnerPlan
from bisheng.common.errcode.linsight import AgentSkillDisabledError
from bisheng.workflow.common.node import BaseNodeData
from bisheng.workflow.graph.graph_state import GraphState
from bisheng.workflow.nodes.agent.agent import AgentNode
from bisheng.workflow.nodes.agent.skill_support import (
    AgentNodeSkillRun,
    AgentNodeSkills,
    AgentSkillRunError,
    format_deliverables,
    parse_agent_skill_error,
)


class _Model(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "fixed"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="answer"))])


class _Callback:
    def __init__(self):
        self.stream_over = []

    def on_stream_over(self, data):
        self.stream_over.append(data)

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


def _params(skills=("docx",), tab="single", output_user=True, input_files=None):
    params = [
        {"key": "model_id", "value": 1},
        {"key": "system_prompt", "value": "你是助手。"},
        {"key": "user_prompt", "value": "写周报"},
        {"key": "chat_history_flag", "value": {"flag": False, "value": 0}},
        {"key": "tool_list", "value": []},
        {"key": "knowledge_id", "value": {"type": "knowledge", "value": []}},
        {"key": "output_user", "value": output_user},
        {"key": "skill_list", "value": [{"key": name, "label": name} for name in skills]},
    ]
    if input_files is not None:
        params.append({"key": "input_files", "value": input_files})
    if tab == "batch":
        params.append({"key": "batch_variable", "value": ["start_1.a", "start_1.b"]})
        params.append({"key": "output", "value": [{"key": "output_a"}, {"key": "output_b"}]})
    return params


@pytest.fixture
def env(monkeypatch):
    executor = {"type": "function call"}
    monkeypatch.setattr(agent_module.LLMService, "get_bisheng_llm_sync", lambda **kwargs: _Model())
    monkeypatch.setattr(
        agent_module.LLMService,
        "sync_get_assistant_llm",
        lambda tenant_id=None: SimpleNamespace(
            llm_list=[
                SimpleNamespace(
                    model_id=1,
                    agent_executor_type=executor["type"],
                    knowledge_max_content=1000,
                    knowledge_sort_index=False,
                )
            ]
        ),
    )
    runs = []

    def _prepare(self, executor_type, tools):
        run = AgentNodeSkillRun(
            runner=None, plan=RunnerPlan(middleware=[], tools=list(tools), skill_names=list(self.skill_names))
        )
        runs.append(run)
        return run

    def _finish(self, run):
        run.files = [{"file_id": f"f{len(runs)}", "file_name": f"r{len(runs)}.docx", "file_url": f"/u/{len(runs)}"}]
        return run.files

    monkeypatch.setattr(AgentNodeSkills, "prepare", _prepare)
    monkeypatch.setattr(AgentNodeSkills, "finish", _finish)
    return SimpleNamespace(executor=executor, runs=runs)


def _node(params, tab="single", chat_id="c1"):
    data = BaseNodeData(
        id="agent_1",
        type="agent",
        name="助手",
        tab={"value": tab},
        group_params=[{"name": "g", "params": params}],
    )
    graph_state = GraphState()
    graph_state.history_memory = ConversationBufferWindowMemory(k=10)
    graph_state.set_variable("start_1", "a", "A")
    graph_state.set_variable("start_1", "b", "B")
    callback = _Callback()
    node = AgentNode(
        node_data=data,
        workflow_id="flow-1",
        user_id=7,
        graph_state=graph_state,
        target_edges=[],
        max_steps=10,
        callback=callback,
        workflow_name="Flow",
        tenant_id=2,
        chat_id=chat_id,
    )
    return node, callback


class TestAgentNodeWithSkills:
    def test_single_run_sets_deliverables_and_sends_files(self, env):
        node, callback = _node(_params())
        result = node._run("exec-1")
        assert result["output"] == "answer"
        assert result["output_deliverables"] == "r1.docx: /u/1"
        (event,) = callback.stream_over
        assert event.files == env.runs[0].files

    def test_deliverables_variable_is_set_even_when_not_shown(self, env):
        node, callback = _node(_params(output_user=False))
        result = node._run("exec-1")
        assert result["output_deliverables"] == "r1.docx: /u/1"
        assert callback.stream_over == []

    def test_batch_runs_keep_their_own_files(self, env):
        node, callback = _node(_params(tab="batch"), tab="batch")
        result = node._run("exec-1")
        assert result["output_a_deliverables"] == "r1.docx: /u/1"
        assert result["output_b_deliverables"] == "r2.docx: /u/2"
        assert [e.files[0]["file_id"] for e in callback.stream_over] == ["f1", "f2"]
        assert len(env.runs) == 2

    def test_run_log_lists_skills_and_the_deliverables_variable(self, env):
        node, _ = _node(_params())
        result = node._run("exec-1")
        (log,) = node.parse_log("exec-1", result)
        keys = [item["key"] for item in log]
        assert "skill_list" in keys
        assert "agent_1.output" in keys
        assert "agent_1.output_deliverables" in keys
        assert next(item["value"] for item in log if item["key"] == "skill_list") == ["docx"]

    def test_react_model_with_skills_fails_with_11077(self, env):
        env.executor["type"] = "ReAct"
        node, _ = _node(_params())
        with pytest.raises(AgentSkillRunError) as exc_info:
            node._run("exec-1")
        payload = parse_agent_skill_error(str(exc_info.value))
        assert payload["status_code"] == 11077


class TestAgentNodeWithoutSkills:
    def test_no_skills_means_no_deliverables_and_no_runner(self, env):
        node, callback = _node(_params(skills=()))
        result = node._run("exec-1")
        assert result == {"output": "answer"}
        assert env.runs == []
        assert callback.stream_over[0].files == []


class TestSkillSupport:
    def _skills(self, chat_id="c1", tmp_session_id=None, params=None):
        node = SimpleNamespace(
            id="agent_1",
            name="助手",
            user_id=7,
            tenant_id=2,
            chat_id=chat_id,
            tmp_session_id=tmp_session_id,
            node_params=params if params is not None else {"skill_list": [{"key": "docx"}]},
            workflow_id="flow-1",
            workflow_name="Flow",
            get_other_node_variable=lambda var: ["http://minio/a/表.xlsx"] if var == "input_1.files" else None,
        )
        return AgentNodeSkills(node)

    def test_formal_session_key_and_target(self):
        skills = self._skills()
        assert skills.workspace_key().svid == "agent/c1/wf-agent_1"
        target = skills.deliverable_target()
        assert target.object_dir == "chat/7/agent/c1"
        assert not target.use_tmp_bucket
        assert target.url_for("f1") == "/api/v1/agent-runtime/files/c1/f1"

    def test_debug_session_key_and_target(self):
        skills = self._skills(chat_id=None, tmp_session_id="t1")
        assert skills.workspace_key().svid == "agent/tmp-t1/wf-agent_1"
        target = skills.deliverable_target()
        assert target.use_tmp_bucket
        assert target.url_for("f1") == "/api/v1/agent-runtime/files/tmp-t1/f1"

    def test_missing_skill_list_means_disabled(self):
        assert not self._skills(params={}).enabled

    def test_input_files_are_downloaded(self, monkeypatch, tmp_path):
        local = tmp_path / "x.xlsx"
        local.write_bytes(b"xls")
        monkeypatch.setattr(support, "file_download", lambda url: (str(local), "表.xlsx"))
        skills = self._skills(params={"skill_list": [{"key": "docx"}], "input_files": ["input_1.files"]})
        assert skills.collect_input_files() == [("表.xlsx", b"xls")]

    def test_user_facing_error_round_trips_through_the_reason(self, monkeypatch):
        def _raise(coro, timeout):
            coro.close()
            raise AgentSkillDisabledError(skill_name="docx")

        monkeypatch.setattr(support, "run_async_safe", _raise)
        monkeypatch.setattr(support.AgentNodeSkills, "collect_input_files", lambda self: [])
        with pytest.raises(AgentSkillRunError) as exc_info:
            self._skills().prepare("function call", [])
        payload = parse_agent_skill_error(str(exc_info.value))
        assert payload["status_code"] == 11075
        assert payload["data"]["skill_name"] == "docx"

    def test_format_deliverables(self):
        files = [{"file_name": "a.docx", "file_url": "/u/1"}, {"file_name": "b.xlsx", "file_url": "/u/2"}]
        assert format_deliverables(files) == "a.docx: /u/1\nb.xlsx: /u/2"
        assert format_deliverables([]) == ""


class TestFailureEvent:
    def test_skill_error_reaches_the_failure_event_with_its_code(self):
        from bisheng.worker.workflow.redis_callback import RedisCallback

        callback = RedisCallback.__new__(RedisCallback)
        callback.user_id, callback.chat_id, callback.workflow_id = 7, "c1", "flow-1"
        reason = str(AgentSkillRunError(AgentSkillDisabledError(skill_name="docx"), "助手"))
        response = callback.parse_workflow_failed({"reason": reason})
        assert response.message["status_code"] == 11075
        assert response.message["data"]["skill_name"] == "docx"

    def test_other_failures_are_unchanged(self):
        from bisheng.worker.workflow.redis_callback import RedisCallback

        callback = RedisCallback.__new__(RedisCallback)
        callback.user_id, callback.chat_id, callback.workflow_id = 7, "c1", "flow-1"
        response = callback.parse_workflow_failed({"reason": "boom"})
        assert response.message["status_code"] != 11075
