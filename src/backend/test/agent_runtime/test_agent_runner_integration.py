"""F078: the real middleware stack on create_agent, with a fake model.

Checks what the model actually receives (design pitfalls 2 and 16): the file
tools are visible, ``execute`` is not, and the skill list reaches the prompt.
"""

from types import SimpleNamespace

import pytest
from langchain.agents import create_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult

import bisheng.agent_runtime.domain.services.agent_runner as runner_module
import bisheng.agent_runtime.domain.services.agent_workspace as workspace_module
import bisheng.linsight.domain.services.skill_provisioning as provisioning
from bisheng.agent_runtime.domain.services.agent_runner import AgentRunner, AgentRunSpec
from bisheng.agent_runtime.domain.services.agent_workspace import WorkspaceKey
from bisheng.agent_runtime.domain.services.code_tool import CodeToolResult, CodeToolStatus
from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from test.linsight.fixtures.fake_minio import FakeMinioStorage


class _RecordingModel(BaseChatModel):
    """Answers once and records the tools and system prompt it was given."""

    seen: dict = {}

    @property
    def _llm_type(self) -> str:
        return "recording"

    def bind_tools(self, tools, **kwargs):
        _RecordingModel.seen["tools"] = [getattr(tool, "name", None) or tool.get("name") for tool in tools]
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        _RecordingModel.seen["system"] = messages[0].content if messages else ""
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="done"))])


class _SkillStore:
    def list_files(self, tenant_id, name, content_hash):
        return [{"path": "SKILL.md", "size": 1}]

    def read_bytes(self, tenant_id, name, content_hash, rel):
        return b"---\nname: docx\ndescription: Make Word documents.\n---\n\nRead me first.\n"


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    _RecordingModel.seen = {}

    async def _resolve(names):
        return [SimpleNamespace(name=name, enabled=1, content_hash="h") for name in names]

    async def _list_enabled():
        return [SimpleNamespace(name="docx", content_hash="h")]

    monkeypatch.setattr(runner_module, "resolve_skills", _resolve)
    monkeypatch.setattr(provisioning.LinsightSkillDao, "list_enabled", _list_enabled)
    monkeypatch.setattr(provisioning, "SkillStore", _SkillStore)
    monkeypatch.setattr(workspace_module, "CACHE_DIR", str(tmp_path))


async def _no_executor(**kwargs):
    return CodeToolResult(tool=None, status=CodeToolStatus.MISSING)


async def test_model_sees_file_tools_and_skills_but_not_execute():
    spec = AgentRunSpec(
        tenant_id=2,
        user_id=7,
        workspace_key=WorkspaceKey.formal("c1", "wf-n1"),
        skill_names=["docx"],
        executor_type="function call",
        tools=[],
        input_files=[],
        app_type=ApplicationTypeEnum.WORKFLOW,
        app_id="flow-1",
        app_name="Flow",
    )
    runner = AgentRunner(spec, minio=FakeMinioStorage(), code_tool_builder=_no_executor)
    plan = await runner.aprepare()
    try:
        agent = create_agent(_RecordingModel(), plan.tools, system_prompt="你是周报助手。", middleware=plan.middleware)
        result = await agent.ainvoke({"messages": [HumanMessage(content="写一份周报")]})
    finally:
        await runner.afinish()

    assert result["messages"][-1].content == "done"
    tools = _RecordingModel.seen["tools"]
    assert {"ls", "read_file", "write_file", "edit_file", "glob", "grep"} <= set(tools)
    assert "execute" not in tools
    system = _RecordingModel.seen["system"]
    # Middleware appends make the system content a list of text blocks.
    system_text = system if isinstance(system, str) else "".join(block.get("text", "") for block in system)
    assert system_text.startswith("你是周报助手。")
    assert "docx" in system_text
    assert "技能使用规则" in system_text
