"""Checked skills are marked in the prompt. A missing tool does not fail the task."""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import MagicMock

from deepagents.backends.filesystem import FilesystemBackend
from langchain_core.messages import SystemMessage

from bisheng.linsight.domain.services.agent_factory import (
    SKILL_SELECTED_NOTE,
    SKILL_TOOL_UNAVAILABLE_NOTE,
    SkillSelectionMiddleware,
    create_linsight_agent,
    task_tool_names,
)
from bisheng.linsight.domain.services.skills_prompt import LinsightSkillsMiddleware


def _skill_md(name: str, description: str, allowed: str | None = None) -> str:
    lines = ["---", f"name: {name}", f"description: {description}"]
    if allowed:
        lines.append(f"allowed-tools: {allowed}")
    lines.extend(["---", "", f"# {name}", ""])
    return "\n".join(lines)


def _write_skill(root, name: str, description: str, allowed: str | None = None) -> tuple[object, bytes]:
    text = _skill_md(name, description, allowed)
    path = root / "skills" / name / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_bytes(text.encode())
    return path, text.encode()


class _Request:
    def __init__(self, state, system_message=None, tool_call=None, tool=None):
        self.state = state
        self.system_message = system_message
        self.tool_call = tool_call
        self.tool = tool

    def override(self, **kwargs):
        return _Request(
            self.state,
            kwargs.get("system_message", self.system_message),
            self.tool_call,
            self.tool,
        )


def _prompt_text(message) -> str:
    parts = []
    for block in message.content_blocks:
        text = block.get("text") if isinstance(block, dict) else getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


def _row(text: str, name: str) -> str:
    return next(line for line in text.splitlines() if line.startswith(f"- **{name}**:"))


def _listed(root, state):
    skills = LinsightSkillsMiddleware(
        backend=FilesystemBackend(root_dir=str(root), virtual_mode=True),
        sources=[("/skills/", "Skills")],
    )
    listed = skills.modify_request(_Request(state, SystemMessage(content="base")))
    return skills, listed


class TestSelectionPrompt:
    def test_checked_directory_is_marked_and_the_file_is_unchanged(self, tmp_path):
        pdf, pdf_bytes = _write_skill(tmp_path, "pdf", "个人用途", allowed="Bash")
        contract, contract_bytes = _write_skill(tmp_path, "he-tong", "审阅合同")
        skills, _ = _listed(tmp_path, {})
        loaded = skills.before_agent({}, MagicMock(), {"configurable": {}})
        # Provisioning already stored the personal directory when the checked id
        # belonged to the covered tenant skill of the same name.
        selection = SkillSelectionMiddleware(selected_names=["pdf"], tool_names={"read_file"})
        request = _Request(loaded, SystemMessage(content="base"))
        listed = skills.modify_request(request)
        shown = selection.wrap_model_call(listed, lambda item: item)
        text = _prompt_text(shown.system_message)

        pdf_line = _row(text, "pdf")
        contract_line = _row(text, "he-tong")
        assert SKILL_SELECTED_NOTE in pdf_line
        assert SKILL_SELECTED_NOTE not in contract_line
        assert "个人用途" in pdf_line
        assert "审阅合同" in contract_line
        assert SKILL_TOOL_UNAVAILABLE_NOTE in pdf_line
        assert SKILL_TOOL_UNAVAILABLE_NOTE not in contract_line
        assert pdf.read_bytes() == pdf_bytes
        assert contract.read_bytes() == contract_bytes

    def test_name_only_request_matches_the_directory(self, tmp_path):
        _write_skill(tmp_path, "pdf", "个人用途")
        _write_skill(tmp_path, "he-tong", "审阅合同")
        skills, _ = _listed(tmp_path, {})
        loaded = skills.before_agent({}, MagicMock(), {"configurable": {}})
        selection = SkillSelectionMiddleware(
            selected_names=["he-tong"], tool_names=task_tool_names([], has_code_interpreter=False)
        )
        shown = selection.wrap_model_call(
            skills.modify_request(_Request(loaded, SystemMessage(content="base"))),
            lambda item: item,
        )
        text = _prompt_text(shown.system_message)
        assert SKILL_SELECTED_NOTE not in _row(text, "pdf")
        assert SKILL_SELECTED_NOTE in _row(text, "he-tong")
        assert SKILL_TOOL_UNAVAILABLE_NOTE not in text

    def test_checkpoint_metadata_is_not_reread_from_disk(self, tmp_path):
        path, _ = _write_skill(tmp_path, "pdf", "原来的用途")
        skills, _ = _listed(tmp_path, {})
        loaded = skills.before_agent({}, MagicMock(), {"configurable": {}})
        path.write_text(_skill_md("pdf", "磁盘上被改掉的用途"), encoding="utf-8")
        assert (
            skills.before_agent({"skills_metadata": loaded["skills_metadata"]}, MagicMock(), {"configurable": {}})
            is None
        )

        selection = SkillSelectionMiddleware(selected_names=["pdf"], tool_names={"read_file"})
        shown = selection.wrap_model_call(
            skills.modify_request(
                _Request({"skills_metadata": loaded["skills_metadata"]}, SystemMessage(content="base"))
            ),
            lambda item: item,
        )
        text = _prompt_text(shown.system_message)
        assert "原来的用途" in text
        assert "磁盘上被改掉的用途" not in text
        assert SKILL_SELECTED_NOTE in _row(text, "pdf")

    def test_calling_a_missing_tool_returns_the_same_sentence(self):
        selection = SkillSelectionMiddleware(selected_names=["pdf"], tool_names={"read_file"})
        request = _Request(
            {"skills_metadata": [{"name": "pdf", "allowed_tools": ["Bash"]}]},
            tool_call={"name": "Bash", "id": "call-1", "args": {}},
            tool=None,
        )

        def handler(_request):
            raise AssertionError("missing tool was executed")

        message = selection.wrap_tool_call(request, handler)
        assert message.content == SKILL_TOOL_UNAVAILABLE_NOTE
        assert "Traceback" not in message.content

    def test_an_undeclared_unknown_tool_still_reaches_the_executor(self):
        selection = SkillSelectionMiddleware(selected_names=["pdf"], tool_names={"read_file"})
        request = _Request(
            {"skills_metadata": [{"name": "pdf", "allowed_tools": ["Bash"]}]},
            tool_call={"name": "made-up", "id": "call-2", "args": {}},
            tool=None,
        )
        seen = {}

        def handler(item):
            seen["name"] = item.tool_call["name"]
            return SimpleNamespace(content="default")

        assert selection.wrap_tool_call(request, handler).content == "default"
        assert seen["name"] == "made-up"

    def test_factory_wraps_the_skills_middleware(self):
        source = inspect.getsource(create_linsight_agent)
        assert source.index("LinsightSkillsMiddleware(") < source.index("SkillSelectionMiddleware(")
