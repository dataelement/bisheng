"""The main prompt must let a selected skill outrank the built-in deliverable path.

Production incident (2026-08-05, task-mode run ``01a799d9…``): the user picked the
``docx`` skill to imitate an attached 公文-format Word file. Everything up to the
model worked — ``skills=["docx"]`` persisted, ``materialize_session_skills`` copied
the bundle, ``SkillsMiddleware`` advertised it — yet the deliverable ignored it.
The transcript shows why: the model wrote ``output/<name>.md`` first, then emitted

    read_file("/skills/docx/SKILL.md")  +  export_docx("output/<name>.md")

as ONE parallel tool-call batch. The skill body arrived after the .docx already
existed, so the skill had zero influence — "selected but never applied", which
reads to the user as "the skill never triggered".

Root cause is a prompt conflict, not a wiring bug: step 3 of the workflow is an
imperative ("markdown 是唯一规范源 … 3c 仅当选了 docx: export_docx"), while skills
rely on the middleware's *progressive disclosure* (read the body only if you think
it applies). An order beats a suggestion. These tests pin the two lines that fix
it, plus the lockstep rule that keeps them out of runs with no skills.
"""

from __future__ import annotations

import pytest

from bisheng.linsight.domain.services.agent_factory import _build_linsight_system_prompt

PLACEHOLDERS = ("__SKILL_EXEC_LINE__", "__SKILL_DELIVERABLE_LINE__", "__KB_EXEC_LINE__", "__KB_DELEGATE_LINE__")


@pytest.mark.parametrize("has_kb", [True, False])
def test_skill_lines_absent_when_no_skill_materialized(has_kb):
    """No bundle copied -> no "Available Skills" section -> never mention skills."""
    prompt = _build_linsight_system_prompt(has_kb, skills_present=False)
    assert "SKILL.md" not in prompt
    assert "技能优先" not in prompt
    # Default must stay the no-skill behaviour: every existing caller passes only has_kb.
    assert _build_linsight_system_prompt(has_kb) == prompt


@pytest.mark.parametrize("has_kb", [True, False])
def test_skill_lines_present_when_a_skill_is_materialized(has_kb):
    prompt = _build_linsight_system_prompt(has_kb, skills_present=True)
    # Step 2: read the body BEFORE producing anything…
    assert "技能优先" in prompt
    assert "SKILL.md" in prompt
    # …and specifically not in the same parallel batch as the deliverable — the
    # exact failure mode observed in production.
    assert "同一轮" in prompt
    # A truncated read is the other observed drift (the model passed limit=200 and
    # never reached the generation steps), so the full read is spelled out.
    assert "limit=1000" in prompt
    # Step 3: a format skill outranks the 3b-3d default derivation path.
    assert "3z" in prompt
    assert "export_docx" in prompt


@pytest.mark.parametrize("has_kb", [True, False])
def test_export_fallback_is_forbidden_when_a_code_executor_is_bound(has_kb):
    """With an executor the skill route is runnable, so the cheap path is banned.

    Deprioritising it was not enough: a run still took write_file + export_docx
    and produced a plain markdown-derived .docx, dropping every layout rule the
    skill specifies.
    """
    prompt = _build_linsight_system_prompt(has_kb, skills_present=True, has_code_interpreter=True)
    # Note: a generic "禁止" also appears in the base template (the "don't claim a
    # file you never wrote" rule), so match the export ban itself.
    assert "**禁止**调用 export_docx" in prompt
    assert "bisheng_code_interpreter" in prompt
    # The ban is not absolute — a repeatedly failing executor may still fall back.
    assert "兜底" in prompt
    # Executor output lands in the local workspace dir, NOT in the object-storage
    # view ls/glob read. Without saying so the model burns turns hunting the file
    # it just wrote (observed: 5 tool calls of ls/glob/shutil before giving up).
    assert "不会**出现在 ls / glob" in prompt


@pytest.mark.parametrize("has_kb", [True, False])
def test_export_fallback_stays_allowed_without_a_code_executor(has_kb):
    """Lockstep: never forbid the only route a run actually has.

    No executor bound -> the skill's script route cannot run, so the 3b-3d
    derivation must remain the sanctioned path.
    """
    prompt = _build_linsight_system_prompt(has_kb, skills_present=True, has_code_interpreter=False)
    assert "没有可用的代码执行工具" in prompt
    assert "**禁止**调用 export_docx" not in prompt
    assert "bisheng_code_interpreter" not in prompt


@pytest.mark.parametrize("has_kb", [True, False])
@pytest.mark.parametrize("skills_present", [True, False])
def test_no_template_placeholder_survives(has_kb, skills_present):
    """A stale placeholder would ship raw ``__SKILL_EXEC_LINE__`` to the model."""
    prompt = _build_linsight_system_prompt(has_kb, skills_present=skills_present)
    for token in PLACEHOLDERS:
        assert token not in prompt


def test_skill_priority_line_precedes_the_default_export_path():
    """Ordering matters: the model reads top-down, so 3z must come before 3a-3d."""
    prompt = _build_linsight_system_prompt(True, skills_present=True)
    assert prompt.index("3z") < prompt.index("3a（始终）")
    # And the skill-reading rule sits in step 2, before the deliverable step.
    assert prompt.index("技能优先") < prompt.index("3. 【产出交付物】")
