"""Ordinary Chat loads selected enterprise skills independently of task routing."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.common.errcode.linsight import SkillNotFoundError, SkillValidationError
from bisheng.linsight.domain.services.skill_store import SkillStore
from bisheng.workstation.domain.services import chat_skills
from test.linsight.fixtures.fake_minio import FakeMinioStorage


@pytest.fixture
def skill_env(tmp_path, monkeypatch):
    store = SkillStore(root=tmp_path / "skills", minio=FakeMinioStorage())
    ref = store.write_bundle(
        1,
        "writing",
        {
            "SKILL.md": b"---\nname: writing\ndescription: writing\n---\nUse the checklist in references/rules.txt.",
            "references/rules.txt": b"Purpose. Audience. Action.",
            "assets/image.png": b"\x89PNG\xff\x00",
        },
    )
    row = SimpleNamespace(name="writing", tenant_id=1, content_hash=ref.content_hash)
    gate = AsyncMock(return_value=[row])
    monkeypatch.setattr(chat_skills.LinsightSkillDao, "list_enabled", gate)
    monkeypatch.setattr(chat_skills, "SkillStore", lambda: store)
    return SimpleNamespace(store=store, gate=gate, row=row)


@pytest.mark.parametrize("selected", [None, []])
async def test_empty_selection_has_no_skill_context(skill_env, selected):
    result = await chat_skills.load_chat_skills(1, 7, selected)
    assert result.instructions == ""
    assert result.tools == []
    skill_env.gate.assert_not_awaited()


async def test_loads_selected_instructions_and_bounded_reference_reader(skill_env):
    result = await chat_skills.load_chat_skills(1, 7, ["writing", "writing"])
    assert result.instructions.count("Use the checklist") == 1
    reader = result.tools[0]
    first = json.loads(await reader.ainvoke({"skill_name": "writing", "path": "references/rules.txt", "limit": 8}))
    assert first["content"] == "Purpose."
    assert first["next_offset"] == 8
    second = json.loads(await reader.ainvoke({"skill_name": "writing", "path": "references/rules.txt", "offset": 8}))
    assert second["content"] == " Audience. Action."
    assert second["next_offset"] is None


@pytest.mark.parametrize("selected,tenant", [(["other"], 1), (["writing"], 2)])
async def test_unknown_or_other_tenant_skill_fails_before_inference(skill_env, selected, tenant):
    with pytest.raises(SkillNotFoundError):
        await chat_skills.load_chat_skills(tenant, 7, selected)


async def test_disabled_skill_fails_before_inference(skill_env):
    skill_env.gate.return_value = []
    with pytest.raises(SkillNotFoundError):
        await chat_skills.load_chat_skills(1, 7, ["writing"])


@pytest.mark.parametrize(
    "args",
    [
        {"skill_name": "other"},
        {"skill_name": "writing", "path": "../SKILL.md"},
        {"skill_name": "writing", "path": "/etc/passwd"},
        {"skill_name": "writing", "path": "missing.txt"},
        {"skill_name": "writing", "path": "assets/image.png"},
    ],
)
async def test_reader_is_scoped_to_selected_text_files(skill_env, args):
    result = await chat_skills.load_chat_skills(1, 7, ["writing"])
    with pytest.raises((SkillNotFoundError, SkillValidationError)):
        await result.tools[0].ainvoke(args)


@pytest.mark.parametrize("change", ["disable", "update", "tenant"])
async def test_reader_rechecks_governance_and_version(skill_env, change):
    result = await chat_skills.load_chat_skills(1, 7, ["writing"])
    if change == "disable":
        skill_env.gate.return_value = []
    elif change == "update":
        skill_env.row.content_hash = "new-version"
    else:
        skill_env.row.tenant_id = 2
    with pytest.raises(SkillNotFoundError):
        await result.tools[0].ainvoke({"skill_name": "writing"})


async def test_broken_skill_stops_the_turn(skill_env, monkeypatch):
    def missing(*args):
        raise FileNotFoundError("missing bundle")

    monkeypatch.setattr(skill_env.store, "read_bytes", missing)
    with pytest.raises(SkillNotFoundError):
        await chat_skills.load_chat_skills(1, 7, ["writing"])


async def test_context_budget_is_explicit(skill_env, monkeypatch):
    monkeypatch.setattr(chat_skills, "MAX_INSTRUCTION_CHARS", 5)
    with pytest.raises(SkillValidationError):
        await chat_skills.load_chat_skills(1, 7, ["writing"])


@pytest.fixture
def stream_env(monkeypatch):
    from bisheng.workstation.domain.services import chat_service

    inserted = []
    monkeypatch.setattr("bisheng.common.image_view.loop.image_view_configured", AsyncMock(return_value=False))
    monkeypatch.setattr(chat_service.DailyCitationScope, "load", AsyncMock())
    monkeypatch.setattr(chat_service, "select_cited_items", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        chat_service,
        "_agent_initialize_chat",
        AsyncMock(
            return_value=(
                SimpleNamespace(systemPrompt=""),
                SimpleNamespace(chat_id="chat-1", user_id=7, name="Test"),
                SimpleNamespace(id=101),
                SimpleNamespace(),
                SimpleNamespace(displayName="test-model"),
                False,
            )
        ),
    )
    monkeypatch.setattr(chat_service, "_resolve_user_kb_selection", AsyncMock(return_value=[]))
    monkeypatch.setattr(chat_service, "_prepare_tools", AsyncMock(return_value=([], [])))
    monkeypatch.setattr(chat_service, "_process_agent_files", AsyncMock(return_value=("", [], [])))
    monkeypatch.setattr(chat_service, "_get_history_max_tokens", AsyncMock(return_value=4096))
    monkeypatch.setattr(
        chat_service, "WorkStationService", SimpleNamespace(get_chat_history=AsyncMock(return_value=[]))
    )
    monkeypatch.setattr(
        chat_service, "DepartmentFlowService", SimpleNamespace(resolve_limit_and_dept=AsyncMock(return_value=(0, None)))
    )
    monkeypatch.setattr(chat_service, "log_telemetry_events", AsyncMock())
    monkeypatch.setattr(chat_service, "save_message_citations", AsyncMock())
    monkeypatch.setattr(chat_service, "save_message_citations_sync", MagicMock())
    monkeypatch.setattr(chat_service.SensitiveWordPolicyService, "is_workbench_content_safety_active", lambda *a: False)

    def record(row):
        row.id = 900 + len(inserted)
        inserted.append(row)
        return row

    monkeypatch.setattr(chat_service.ChatMessageDao, "insert_one", MagicMock(side_effect=record))
    monkeypatch.setattr(chat_service.ChatMessageDao, "ainsert_one", AsyncMock(side_effect=record))
    return inserted


async def test_ordinary_stream_receives_skill_body_and_reference_tool(skill_env, stream_env, monkeypatch):
    from bisheng.workstation.domain.schemas.chat import APIChatCompletion
    from bisheng.workstation.domain.services import chat_service

    seen = {}

    class Agent:
        async def astream_events(self, state, **kwargs):
            seen["messages"] = state["messages"]
            yield {
                "event": "on_chat_model_stream",
                "data": {"chunk": SimpleNamespace(content="Skill applied.", additional_kwargs={})},
            }

    def create_agent(model, tool_node, **kwargs):
        seen["tools"] = tool_node.tools_by_name
        return Agent()

    monkeypatch.setattr("langgraph.prebuilt.create_react_agent", create_agent)
    monkeypatch.setattr(chat_service, "VisionToolBindWrapper", lambda llm, *a, **k: llm)
    monkeypatch.setattr(chat_service, "_get_agent_max_iterations", AsyncMock(return_value=10))
    monkeypatch.setattr(chat_service.SensitiveWordPolicyService, "evaluate_workbench_user_text", lambda *a, **k: None)
    task = AsyncMock()
    monkeypatch.setattr(chat_service, "_task_mode_stream_completion", task)
    data = APIChatCompletion(
        clientTimestamp="t",
        conversationId="chat-1",
        model="m1",
        text="Write a note.",
        task_mode=False,
        skills=["writing"],
    )
    response = await chat_service.stream_chat_completion(MagicMock(), data, SimpleNamespace(user_id=7, tenant_id=1))
    chunks = "".join([chunk async for chunk in response.body_iterator])
    assert "Skill applied." in chunks
    assert "Use the checklist in references/rules.txt." in seen["messages"][-1].content
    assert "Write a note." in seen["messages"][-1].content
    assert "read_skill_file" in seen["tools"]
    assert "linsight_task_handoff" not in chunks
    task.assert_not_awaited()
