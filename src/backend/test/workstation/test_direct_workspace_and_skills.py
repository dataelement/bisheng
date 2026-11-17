"""F004 T052: workspace and skills of a ``direct`` run (design 决策 10; AC-25, AC-33, AC-45, AC-46).

The REAL graph from ``create_linsight_agent(profile="direct")`` runs with the
scripted model of ``test_direct_run``. The code interpreter is a stand-in with
the two properties of the real executor that matter here: it runs in
``local_sync_path`` only when that directory exists, and it mirrors what it
wrote into ``workspace_prefix`` of the object store.
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from pydantic import BaseModel

from bisheng.linsight.domain import task_exec
from bisheng.linsight.domain.services import skill_provisioning, tool_assembly
from bisheng.linsight.domain.services.skill_provisioning import SkillProvisionResult
from bisheng.linsight.domain.services.workbench_impl import LinsightWorkbenchImpl
from bisheng.workstation.domain.services.direct_run import DirectRunner
from test.workstation.test_direct_run import CID, TENANT, USER, _call, make_env  # noqa: F401

CODE_TOOL = tool_assembly.CODE_INTERPRETER_TOOL_KEY
CODE_PAYLOAD = {"id": 9, "tool_key": CODE_TOOL, "type": "tool"}


class _CodeArgs(BaseModel):
    python_code: str


class _FakeExecutor:
    """Runs "code" in ``local_sync_path`` and mirrors ``output/`` like ``sync_to_workspace``."""

    def __init__(self, store: Any, local_sync_path: str, workspace_prefix: str):
        self.store = store
        self.local_sync_path = local_sync_path
        self.workspace_prefix = workspace_prefix
        self.runs: list[dict] = []

    async def arun(self, code: str) -> dict:
        root = self.local_sync_path
        if not os.path.isdir(root):
            # The real local executor falls back to a temporary directory here.
            self.runs.append({"in_workspace": False, "files": []})
            return {"exitcode": 1, "log": "no workspace directory", "file_list": []}
        files = sorted(
            os.path.relpath(os.path.join(base, name), root).replace(os.sep, "/")
            for base, _dirs, names in os.walk(root)
            for name in names
        )
        self.runs.append({"in_workspace": True, "files": files})
        os.makedirs(os.path.join(root, "output"), exist_ok=True)
        with open(os.path.join(root, "output", "chart.txt"), "wb") as fh:
            fh.write(b"chart")
        self.store.objects[f"{self.workspace_prefix}/output/chart.txt"] = b"chart"
        return {"exitcode": 0, "log": "ok", "file_list": []}


class _FakeCodeTool(BaseTool):
    name: str = CODE_TOOL
    description: str = "Run python code in the workspace."
    args_schema: type[BaseModel] = _CodeArgs
    executor: Any = None

    def _run(self, python_code: str) -> dict:
        raise AssertionError("the code interpreter must be called asynchronously")

    async def _arun(self, python_code: str) -> dict:
        return await self.executor.arun(python_code)


class _Binder:
    """Stands in for ``LinsightWorkbenchImpl._init_bisheng_code_tool`` and records how it was called."""

    def __init__(self, store: Any):
        self.store = store
        self.calls: list[dict] = []
        self.executor: _FakeExecutor | None = None

    async def __call__(self, selected_tool_ids, file_dir, user_id, session_version_id=None):
        self.calls.append(
            {
                "selected": list(selected_tool_ids),
                "file_dir": file_dir,
                "user_id": user_id,
                "session_version_id": session_version_id,
            }
        )
        self.executor = _FakeExecutor(self.store, file_dir, f"workspace/{session_version_id}")
        return [_FakeCodeTool(executor=self.executor)]


def _real_assembly(env, monkeypatch: pytest.MonkeyPatch) -> tuple[DirectRunner, _Binder]:
    """A runner that uses the default tool assembly, with the tool binder replaced."""
    binder = _Binder(env.store)
    monkeypatch.setattr(LinsightWorkbenchImpl, "_init_bisheng_code_tool", binder)

    async def object_store():
        return env.store

    # ``_sync_workspace_originals`` resolves the object store itself.
    monkeypatch.setattr(task_exec, "get_minio_storage", object_store)
    runner = env.make_runner(assemble=None)
    return runner, binder


RUN_CODE = _call(CODE_TOOL, {"python_code": "print(1)"}, "code-1")


async def test_code_output_lands_in_conversation_workspace(make_env, monkeypatch: pytest.MonkeyPatch):  # noqa: F811
    env = make_env([RUN_CODE, AIMessage(content="图表已生成")])
    runner, binder = _real_assembly(env, monkeypatch)
    ctx = await env.submit("画一张图")
    ctx.tools = [CODE_PAYLOAD]

    assert (await env.run(ctx, runner)).status == "finished"

    # The interpreter is bound the deep-research way: local cache directory of
    # the conversation, workspace prefix of the conversation.
    assert binder.calls == [{"selected": [9], "file_dir": env.file_dir, "user_id": USER, "session_version_id": CID}]
    assert binder.executor.runs == [{"in_workspace": True, "files": []}]
    assert env.store.objects[f"workspace/{CID}/output/chart.txt"] == b"chart"
    # The file tools of the same run read that workspace.
    tool_messages = [m for m in env.model.inputs[-1] if isinstance(m, ToolMessage)]
    assert tool_messages and "no workspace directory" not in str(tool_messages[-1].content)


async def test_skills_available_in_direct(make_env, monkeypatch: pytest.MonkeyPatch):  # noqa: F811
    body = "---\nname: demo-skill\ndescription: 生成演示报告\n---\n\n# demo-skill\n按三步写报告。\n"
    calls: list[dict] = []

    async def materialize(backend, tenant_id, selected, store=None, **kwargs):
        calls.append({"tenant_id": tenant_id, "selected": list(selected or []), "user_id": kwargs.get("user_id")})
        responses = await backend.aupload_files([("/skills/demo-skill/SKILL.md", body.encode())])
        assert not [r for r in responses if getattr(r, "error", None)]
        return SkillProvisionResult(["demo-skill"], [], None, None)

    monkeypatch.setattr(skill_provisioning, "materialize_session_skills", materialize)
    env = make_env(
        [
            _call("read_file", {"file_path": "/skills/demo-skill/SKILL.md"}, "r1"),
            AIMessage(content="按技能写好了"),
        ]
    )
    ctx = await env.submit("用技能写报告")
    ctx.skills = ["demo-skill"]

    assert (await env.run(ctx)).status == "finished"

    assert calls == [{"tenant_id": TENANT, "selected": ["demo-skill"], "user_id": USER}]
    # Mounted: the bundle is in the workspace of the conversation.
    assert f"workspace/{CID}/skills/demo-skill/SKILL.md" in env.store.objects
    # Advertised: the system prompt of the first model request lists the skill.
    system = "\n".join(str(m.content) for m in env.model.inputs[0] if isinstance(m, SystemMessage))
    assert "demo-skill" in system and "生成演示报告" in system
    # Callable: the model read the skill body through the workspace file tool.
    read_back = [m for m in env.model.inputs[-1] if isinstance(m, ToolMessage)]
    assert "按三步写报告" in str(read_back[-1].content)


async def test_no_skills_selected_mounts_nothing(make_env, monkeypatch: pytest.MonkeyPatch):  # noqa: F811
    async def materialize(*args, **kwargs):
        raise AssertionError("no skill was selected: nothing may be materialised")

    monkeypatch.setattr(skill_provisioning, "materialize_session_skills", materialize)
    env = make_env([AIMessage(content="你好")])

    assert (await env.run(await env.submit("你好"))).status == "finished"

    assert env.store.objects == {}
    assert not os.path.exists(env.file_dir)


async def test_lazy_workspace_creation(make_env, monkeypatch: pytest.MonkeyPatch):  # noqa: F811
    env = make_env([AIMessage(content="不需要运行代码")])
    runner, binder = _real_assembly(env, monkeypatch)
    listed: list[str] = []
    real_list = env.store.list_objects

    def list_objects(bucket, prefix="", recursive=False):
        listed.append(prefix)
        return real_list(bucket, prefix, recursive)

    env.store.list_objects = list_objects
    env.store.objects[f"workspace/{CID}/output/earlier.csv"] = b"a,b\n"
    seen: dict[str, bool] = {}

    async def reply(messages):
        seen["dir_at_model_call"] = os.path.exists(env.file_dir)
        return AIMessage(content="不需要运行代码")

    env.model.script = [reply]
    ctx = await env.submit("一加一等于几")
    ctx.tools = [CODE_PAYLOAD]

    assert (await env.run(ctx, runner)).status == "finished"

    # The interpreter is bound, but it never ran: no local directory was created
    # and the workspace was not read.
    assert len(binder.calls) == 1 and binder.executor.runs == []
    assert seen["dir_at_model_call"] is False
    assert not os.path.exists(env.file_dir)
    assert listed == []


async def test_resume_on_other_node_restores_files(make_env, monkeypatch: pytest.MonkeyPatch):  # noqa: F811
    env = make_env([RUN_CODE, AIMessage(content="算好了")])
    runner, binder = _real_assembly(env, monkeypatch)
    # What an earlier execution on another node left in object storage. This
    # node has no local directory of the conversation.
    env.store.objects.update(
        {
            f"workspace/{CID}/output/earlier.csv": b"a,b\n1,2\n",
            f"workspace/{CID}/uploads/data.xlsx": b"PK\x03\x04xlsx",
            f"workspace/{CID}/uploads/data.md": b"# view\n",
            f"workspace/{CID}/scratch/tmp.txt": b"tmp",
        }
    )
    assert not os.path.exists(env.file_dir)
    ctx = await env.submit("接着算")
    ctx.tools = [CODE_PAYLOAD]

    assert (await env.run(ctx, runner)).status == "finished"

    # Before the code ran, output/ and the raw upload were fetched; the markdown
    # view and scratch/ stay in object storage.
    assert binder.executor.runs == [{"in_workspace": True, "files": ["output/earlier.csv", "uploads/data.xlsx"]}]
