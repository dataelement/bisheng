"""F075 — the daily chat citation rules.

The run-time swap of the legacy section in saved workbench prompts is gone: the
saved ``systemPrompt`` is no longer read (F004 design 决策 15), so the rules come
only from code.
"""

from bisheng.citation.domain.services.citation_handle_service import HANDLE_RULES_HEADER
from bisheng.citation.domain.services.daily_citation_handles import (
    ensure_daily_handle_rules,
    load_daily_handle_rules,
)


def test_prompt_without_rules_gets_them_appended():
    out = ensure_daily_handle_rules("你是一个助手。")
    assert out == f"你是一个助手。\n\n{load_daily_handle_rules()}"


def test_rules_are_appended_once():
    once = ensure_daily_handle_rules("你是一个助手。")
    assert ensure_daily_handle_rules(once) == once
    assert once.count(HANDLE_RULES_HEADER) == 1


def test_empty_prompt_gets_the_rules_alone():
    assert ensure_daily_handle_rules("") == load_daily_handle_rules()
    assert ensure_daily_handle_rules(None) == load_daily_handle_rules()


def test_daily_rules_teach_handles_not_ids():
    rules = load_daily_handle_rules()
    assert rules.startswith(HANDLE_RULES_HEADER)
    assert "[S3]" in rules
    assert "knowledgesearch_" not in rules
    assert "" not in rules
    # the task-mode wording about deliverable files must not leak into daily chat
    assert "output/" not in rules
