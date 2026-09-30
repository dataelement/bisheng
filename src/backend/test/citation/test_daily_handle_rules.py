"""F072 — daily chat citation rules and the run-time swap of the legacy section.

Tenants saved the shipped default system prompt, whose "# 引用规则" section
teaches the model to copy ``<chunk_id>`` ids between private-use markers. Under
the handle contract that section is swapped for the handle rules at run time,
without touching the stored prompt.

The synthetic fixtures below mirror the section layout of the templates that
shipped before F072 (the saved copies in tenants' configs); the last test runs
the swap over the live platform locale files as well. The trap it pins: the
"## 其他信息" sub-section under the legacy heading carries ``{cur_date}`` and
must survive the swap.

AC-02, AC-03.
"""

import json
from pathlib import Path

import pytest

from bisheng.citation.domain.services.citation_handle_service import HANDLE_RULES_HEADER
from bisheng.citation.domain.services.daily_citation_handles import (
    ensure_daily_handle_rules,
    load_daily_handle_rules,
    replace_legacy_citation_rules,
)


def _legacy_prompt(heading: str, subs: tuple[str, str, str], other: str) -> str:
    return (
        "# Role\nYou are an assistant.\n\n"
        "# Rendering Rules\n## 1. Image Rendering\nKeep images.\n\n"
        f"# {heading}\nCite sources at the end of the paragraph.\n\n"
        f"## {subs[0]}\nKnowledge results carry the id in `<chunk_id>` (e.g. `knowledgesearch_18f5868b:0`); "
        "web results in `citation_key`.\n\n"
        f"## {subs[1]}\n- `\\ue200`: start\n- `\\ue201`: separator\n- `\\ue202`: end\n\n"
        f"## {subs[2]}\n1. Put the marker at the end.\n"
        "`Example.\\ue200websearch_3a1c9f22:0\\ue202`\n\n"
        f"## {other}\nCurrent time: {{cur_date}}.\n"
    )


LOCALES = {
    "zh": _legacy_prompt("引用规则", ("来源 ID", "标记格式", "使用要求"), "其他信息"),
    "en": _legacy_prompt("Citation Rules", ("Source ID", "Format", "Requirements"), "Other"),
    "ja": _legacy_prompt("引用ルール", ("ソースID", "フォーマット", "要件"), "その他"),
}


@pytest.mark.parametrize("lang", sorted(LOCALES))
def test_legacy_section_is_swapped_for_handle_rules(lang):
    out = replace_legacy_citation_rules(LOCALES[lang])

    assert HANDLE_RULES_HEADER in out
    assert "<chunk_id>" not in out
    assert "citation_key" not in out
    assert "\\ue200" not in out
    for ch in ("", "", ""):
        assert ch not in out


@pytest.mark.parametrize("lang", sorted(LOCALES))
def test_date_subsection_and_other_sections_survive(lang):
    out = replace_legacy_citation_rules(LOCALES[lang])

    assert "{cur_date}" in out
    assert "# Role\nYou are an assistant." in out
    assert "## 1. Image Rendering\nKeep images." in out


@pytest.mark.parametrize("lang", sorted(LOCALES))
def test_swap_is_idempotent(lang):
    once = replace_legacy_citation_rules(LOCALES[lang])
    assert replace_legacy_citation_rules(once) == once
    assert once.count(HANDLE_RULES_HEADER) == 1


def test_edited_legacy_wording_without_heading_gets_rules_appended():
    prompt = "你是助手。请把 <chunk_id> 里的 id 用 \\ue200 包起来。"
    out = replace_legacy_citation_rules(prompt)

    assert out.startswith(prompt)
    assert out.rstrip().endswith(load_daily_handle_rules())


def test_prompt_without_any_rules_gets_them_appended():
    out = replace_legacy_citation_rules("你是一个助手。")
    assert out == f"你是一个助手。\n\n{load_daily_handle_rules()}"


def test_empty_prompt_gets_the_rules_alone():
    assert replace_legacy_citation_rules(None) == load_daily_handle_rules()
    assert ensure_daily_handle_rules("") == load_daily_handle_rules()


def test_daily_rules_teach_handles_not_ids():
    rules = load_daily_handle_rules()
    assert rules.startswith(HANDLE_RULES_HEADER)
    assert "[S3]" in rules
    assert "knowledgesearch_" not in rules
    assert "" not in rules
    # the task-mode wording about deliverable files must not leak into daily chat
    assert "output/" not in rules


LOCALE_DIR = Path(__file__).resolve().parents[3] / "frontend" / "platform" / "public" / "locales"


@pytest.mark.parametrize("lang", ["zh-Hans", "en-US", "ja"])
def test_shipped_default_template_already_teaches_handles(lang):
    """AC-04: the shipped default templates carry the handle rules in their own
    language, so the run-time swap leaves them untouched (no second, Chinese
    copy appended) and they never mention the verbatim-id format."""
    data = json.loads((LOCALE_DIR / lang / "bs.json").read_text(encoding="utf-8"))
    template = data["chatConfig"]["systemPrompt2"]

    assert replace_legacy_citation_rules(template) == template
    assert template.count("[S3][S7]") == 1
    assert "<chunk_id>" not in template
    assert "citation_key" not in template
    assert "\\ue200" not in template
    assert "{cur_date}" in template
