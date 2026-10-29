# ruff: noqa: RUF001 - Chinese prompt text, full-width punctuation is intended
"""Task mode's skills section: Chinese, and it says where SKILL.md paths are rooted.

Incident 2026-10-23 (svid 4c85fb69…): SKILL.md listed ``references/…`` files, the
model read ``/references/…`` three times, got "not found" each time, and redid a
30k-character analysis after every miss.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from deepagents.backends.filesystem import FilesystemBackend
from langchain_core.messages import SystemMessage

from bisheng.linsight.domain.services.agent_factory import SKILL_SELECTED_NOTE, SkillSelectionMiddleware
from bisheng.linsight.domain.services.skills_prompt import LINSIGHT_SKILLS_HEADING, LinsightSkillsMiddleware


class _Request:
    def __init__(self, state, system_message=None):
        self.state = state
        self.system_message = system_message

    def override(self, **kwargs):
        return _Request(self.state, kwargs.get("system_message", self.system_message))


def _write_skill(root, name: str, description: str, extra: str = "") -> None:
    path = root / "skills" / name / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text(f"---\nname: {name}\ndescription: {description}\n{extra}---\n\n# {name}\n", encoding="utf-8")


def _text(message) -> str:
    return "\n".join(block["text"] for block in message.content_blocks if block.get("text"))


def _render(root, selected: list[str] | None = None) -> str:
    skills = LinsightSkillsMiddleware(
        backend=FilesystemBackend(root_dir=str(root), virtual_mode=True),
        sources=[("/skills/", "Skills")],
    )
    loaded = skills.before_agent({}, MagicMock(), {"configurable": {}})
    request = skills.modify_request(_Request(loaded, SystemMessage(content="base")))
    if selected is not None:
        request = SkillSelectionMiddleware(selected_names=selected, tool_names={"read_file"}).wrap_model_call(
            request, lambda item: item
        )
    return _text(request.system_message)


def test_section_states_that_skill_paths_are_rooted_at_the_skill_folder(tmp_path):
    _write_skill(tmp_path, "credit-report-llm-refresh", "刷新评级报告")
    text = _render(tmp_path)

    assert f"**{LINSIGHT_SKILLS_HEADING}：**" in text
    assert "`/skills/<技能名>/`" in text
    assert "/skills/<技能名>/references/rules.md" in text
    assert "- **credit-report-llm-refresh**: 刷新评级报告" in text
    assert "完整说明：`/skills/credit-report-llm-refresh/SKILL.md`" in text


def test_framework_text_that_does_not_apply_is_gone(tmp_path):
    _write_skill(tmp_path, "pdf", "处理 PDF")
    text = _render(tmp_path)

    for leftover in ("Skills Skills", "Deepagents", "web-research", "for full instructions", "Available Skills"):
        assert leftover not in text


def test_allowed_tools_and_license_still_render(tmp_path):
    _write_skill(tmp_path, "pdf", "处理 PDF", extra="license: MIT\nallowed-tools: Bash\n")
    text = _render(tmp_path)

    assert "- **pdf**: 处理 PDF (License: MIT)" in text
    assert "需要的工具：Bash" in text


def test_selection_note_still_lands_on_the_row(tmp_path):
    _write_skill(tmp_path, "pdf", "处理 PDF")
    _write_skill(tmp_path, "he-tong", "审阅合同")
    rows = {
        line.split("**")[1]: line
        for line in _render(tmp_path, selected=["pdf"]).splitlines()
        if line.startswith("- **")
    }

    assert SKILL_SELECTED_NOTE in rows["pdf"]
    assert SKILL_SELECTED_NOTE not in rows["he-tong"]


def test_name_matches_the_framework_class_for_checkpoint_resume():
    middleware = LinsightSkillsMiddleware(backend=MagicMock(), sources=[("/skills/", "Skills")])
    assert middleware.name == "SkillsMiddleware"
