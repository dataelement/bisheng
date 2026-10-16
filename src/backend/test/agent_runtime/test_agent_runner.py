"""F078 T19: AgentRunner prepares and finishes one skill-capable run."""

from types import SimpleNamespace

import pytest

import bisheng.agent_runtime.domain.services.agent_runner as runner_module
from bisheng.agent_runtime.domain.services.agent_runner import AgentRunner, AgentRunSpec
from bisheng.agent_runtime.domain.services.agent_workspace import WorkspaceKey
from bisheng.agent_runtime.domain.services.code_tool import CodeToolResult, CodeToolStatus
from bisheng.agent_runtime.domain.services.deliverables import DeliverableTarget
from bisheng.agent_runtime.domain.services.skill_prompt_middleware import SkillPromptMiddleware, SkillPromptVariant
from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from bisheng.common.errcode.linsight import AgentSkillExecutorUnsupportedError
from bisheng.core.context.tenant import get_current_tenant_id


class _Tool:
    def __init__(self, name):
        self.name = name
        self.closed = False

    def close(self):
        self.closed = True


class _FakeWorkspace:
    instances: list = []

    def __init__(self, key, minio, tenant_id, **kwargs):
        self.key = key
        self.tenant_id = tenant_id
        self.file_dir = f"/tmp/fake/{key.svid}"
        self.run_id = "run-1"
        self.cleaned = False
        self.deleted = False
        self.prepared_with = None
        _FakeWorkspace.instances.append(self)

    async def aprepare(self, skills, input_files):
        self.prepared_with = ([row.name for row in skills], list(input_files))
        self.tenant_seen = get_current_tenant_id()
        return SimpleNamespace(
            backend=SimpleNamespace(name="backend"),
            file_dir=self.file_dir,
            baseline={},
            skill_names=[row.name for row in skills],
        )

    def cleanup_local(self):
        self.cleaned = True

    async def adelete(self):
        self.deleted = True
        return 1


@pytest.fixture(autouse=True)
def _fakes(monkeypatch):
    _FakeWorkspace.instances = []
    monkeypatch.setattr(runner_module, "AgentWorkspace", _FakeWorkspace)

    async def _resolve(names):
        return [SimpleNamespace(name=name, enabled=1) for name in names or []]

    monkeypatch.setattr(runner_module, "resolve_skills", _resolve)

    released = []
    monkeypatch.setattr(runner_module, "release_local_run", lambda work_dir: released.append(work_dir))

    collected = {}

    async def _collect(minio, file_dir, baseline, target):
        collected["file_dir"] = file_dir
        return [{"file_id": "f1", "file_name": "a.docx"}]

    monkeypatch.setattr(runner_module, "acollect_deliverables", _collect)
    # Middleware construction is exercised separately; here only its order matters.
    monkeypatch.setattr(runner_module, "_filesystem_middleware", lambda backend: SimpleNamespace(name="Filesystem"))
    monkeypatch.setattr(runner_module, "_skills_middleware", lambda file_dir: SimpleNamespace(name="Skills"))
    monkeypatch.setattr(
        runner_module, "_repair_middleware", lambda tools: SimpleNamespace(name="Repair", tools=list(tools))
    )
    return SimpleNamespace(released=released, collected=collected)


def _code_tool_builder(status=CodeToolStatus.READY):
    async def _build(**kwargs):
        if status is CodeToolStatus.READY:
            return CodeToolResult(tool=_Tool("bisheng_code_interpreter"), status=status)
        return CodeToolResult(tool=None, status=status, reason="nope")

    return _build


def _spec(skills=("docx",), executor="function call", tools=(), text_only=False, target=True):
    return AgentRunSpec(
        tenant_id=2,
        user_id=7,
        workspace_key=WorkspaceKey.formal("c1", "wf-n1"),
        skill_names=list(skills) if skills is not None else None,
        executor_type=executor,
        tools=list(tools),
        input_files=[("in.xlsx", b"x")],
        app_type=ApplicationTypeEnum.WORKFLOW,
        app_id="flow-1",
        app_name="Flow",
        text_only=text_only,
        deliverable_target=DeliverableTarget("chat/7/agent/c1", False, lambda fid: fid) if target else None,
    )


def _runner(spec, status=CodeToolStatus.READY):
    return AgentRunner(spec, minio=SimpleNamespace(), code_tool_builder=_code_tool_builder(status))


class TestNoSkills:
    @pytest.mark.parametrize("skills", [None, []])
    async def test_no_skills_means_no_middleware_and_no_workspace(self, skills):
        tools = [_Tool("web_search")]
        runner = _runner(_spec(skills=skills, tools=tools))
        plan = await runner.aprepare()
        assert plan.middleware == []
        assert plan.tools == tools
        assert plan.notices == []
        assert _FakeWorkspace.instances == []
        assert await runner.afinish() == []

    async def test_react_without_skills_is_fine(self):
        plan = await _runner(_spec(skills=None, executor="ReAct")).aprepare()
        assert plan.middleware == []


class TestWithSkills:
    async def test_react_with_skills_raises_11063(self):
        with pytest.raises(AgentSkillExecutorUnsupportedError):
            await _runner(_spec(executor="ReAct")).aprepare()
        assert _FakeWorkspace.instances == []

    async def test_middleware_order_and_tools(self):
        plan = await _runner(_spec(tools=[_Tool("web_search")])).aprepare()
        names = [m.name for m in plan.middleware]
        assert names == ["Filesystem", "Skills", "AgentSkillPrompt", "Repair"]
        assert [t.name for t in plan.tools] == ["web_search", "bisheng_code_interpreter"]
        prompt = plan.middleware[2]
        assert isinstance(prompt, SkillPromptMiddleware)
        assert plan.prompt_variant is SkillPromptVariant.WITH_EXECUTOR
        assert plan.skill_names == ["docx"]
        assert plan.notices == []

    async def test_workspace_gets_skills_inputs_and_tenant_context(self):
        await _runner(_spec()).aprepare()
        (ws,) = _FakeWorkspace.instances
        assert ws.prepared_with == (["docx"], [("in.xlsx", b"x")])
        assert ws.tenant_seen == 2

    async def test_user_added_code_interpreter_is_replaced_not_duplicated(self):
        plan = await _runner(_spec(tools=[_Tool("bisheng_code_interpreter"), _Tool("web_search")])).aprepare()
        names = [t.name for t in plan.tools]
        assert names.count("bisheng_code_interpreter") == 1
        assert "web_search" in names

    @pytest.mark.parametrize("status", [CodeToolStatus.MISSING, CodeToolStatus.ERROR])
    async def test_unavailable_executor_adds_a_notice(self, status):
        plan = await _runner(_spec(), status=status).aprepare()
        assert plan.notices == ["code_executor_missing"]
        assert plan.prompt_variant is SkillPromptVariant.NO_EXECUTOR
        assert "bisheng_code_interpreter" not in [t.name for t in plan.tools]

    async def test_text_only_uses_the_text_only_prompt(self):
        plan = await _runner(_spec(text_only=True, target=False)).aprepare()
        assert plan.prompt_variant is SkillPromptVariant.TEXT_ONLY


class TestFinish:
    async def test_finish_collects_and_cleans_up(self, _fakes):
        runner = _runner(_spec())
        plan = await runner.aprepare()
        code_tool = plan.tools[-1]
        files = await runner.afinish()
        (ws,) = _FakeWorkspace.instances
        assert files == [{"file_id": "f1", "file_name": "a.docx"}]
        assert code_tool.closed
        assert _fakes.released == [ws.file_dir]
        assert ws.cleaned

    async def test_finish_cleans_up_when_collection_fails(self, monkeypatch, _fakes):
        async def _boom(*args, **kwargs):
            raise RuntimeError("storage down")

        monkeypatch.setattr(runner_module, "acollect_deliverables", _boom)
        runner = _runner(_spec())
        plan = await runner.aprepare()
        with pytest.raises(RuntimeError):
            await runner.afinish()
        (ws,) = _FakeWorkspace.instances
        assert plan.tools[-1].closed
        assert ws.cleaned

    async def test_finish_without_target_collects_nothing(self, _fakes):
        runner = _runner(_spec(text_only=True, target=False))
        await runner.aprepare()
        assert await runner.afinish() == []
        assert "file_dir" not in _fakes.collected

    async def test_once_workspace_is_deleted_after_the_run(self):
        spec = _spec(target=False, text_only=True)
        spec.workspace_key = WorkspaceKey.once("assistant")
        runner = _runner(spec)
        await runner.aprepare()
        await runner.afinish()
        (ws,) = _FakeWorkspace.instances
        assert ws.deleted

    async def test_finish_is_safe_without_prepare(self):
        assert await _runner(_spec()).afinish() == []
