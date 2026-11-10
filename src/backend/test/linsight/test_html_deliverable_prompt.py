"""Step 3 of the task-mode prompt: when the markdown file is written, and how html ships.

Production case (cofco session a4b4a014, 2026-10-21): the user chose html only, the
run had no knowledge base or web search, and the old "3a（始终）" rule still made
the model write the whole report twice — md first (143 s), html second (152 s) —
for a markdown file nobody asked for.

The markdown file has exactly two jobs: it is the source export_docx / export_pdf
convert from, and it is the only file the citation audit reads. So it is skipped
only when html is the sole format AND the run cannot cite anything. Whether the
run can cite is known when the prompt is built, so that half of the condition is
resolved in code; only the user's format choice is left to the model.
"""

from __future__ import annotations

import pytest

from bisheng.linsight.domain.services.agent_factory import _build_linsight_system_prompt

SKIP_MD = "只选了 html 时跳过，不写 md"


def _step3(prompt: str) -> str:
    return prompt[prompt.index("3. 【产出交付物】") : prompt.index("4. 【收尾】")]


def test_md_is_skipped_for_html_only_when_nothing_can_be_cited():
    step = _step3(_build_linsight_system_prompt(False))
    assert "3a（始终）" not in step
    assert SKIP_MD in step
    # md is still required for every format that is derived from it.
    assert "选了 markdown、docx 或 pdf 之一时" in step
    assert "只选了 html 时，html 就是唯一交付物" in step


@pytest.mark.parametrize(
    ("has_kb", "has_web"),
    [(True, False), (False, True), (True, True)],
)
def test_md_is_always_written_when_the_run_can_cite(has_kb, has_web):
    """The citation audit reads .md only; html-only would ship unaudited [Sn] handles."""
    step = _step3(_build_linsight_system_prompt(has_kb, has_web_search=has_web))
    assert "3a（始终）" in step
    assert SKIP_MD not in step
    assert "来源标注以 md 为准" in step


@pytest.mark.parametrize("has_kb", [True, False])
def test_docx_and_pdf_still_derive_from_markdown(has_kb):
    step = _step3(_build_linsight_system_prompt(has_kb))
    assert 'export_docx(source_path="output/<name>.md")' in step
    assert 'export_pdf(source_path="output/<name>.md")' in step


@pytest.mark.parametrize("has_kb", [True, False])
def test_html_rule_names_the_offline_constraint_and_the_checker(has_kb):
    prompt = _build_linsight_system_prompt(has_kb)
    step = _step3(prompt)
    assert "不引用任何外部地址或相对路径" in step
    assert 'check_html(path="output/<name>.html")' in step
    assert "最多修 2 轮" in step
    # The tool is advertised in the tool list too (it is bound with the export tools).
    assert "- check_html(path)" in prompt


@pytest.mark.parametrize("has_code_interpreter", [True, False])
def test_format_skill_rule_covers_html_and_defers_to_the_md_condition(has_code_interpreter):
    prompt = _build_linsight_system_prompt(False, skills_present=True, has_code_interpreter=has_code_interpreter)
    step = _step3(prompt)
    assert "docx / xlsx / pptx / html" in step
    # The old wording forced md unconditionally and would undo the html-only rule.
    assert "3a 的 markdown 规范源仍然要写" not in step
    assert "3a 的 markdown 按 3a 的条件写" in step


@pytest.mark.parametrize("has_kb", [True, False])
@pytest.mark.parametrize("unattended", [True, False])
def test_no_new_placeholder_survives(has_kb, unattended):
    prompt = _build_linsight_system_prompt(has_kb, unattended=unattended)
    assert "__MD_DELIVERABLE_CONDITION__" not in prompt
    assert "__HTML_ONLY_LINE__" not in prompt
