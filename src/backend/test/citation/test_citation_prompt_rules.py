# ruff: noqa: RUF001 - the fullwidth colon mirrors the real locale rule text
"""Citation rules have exactly one source (citation.yaml) and one backstop.

Guards the two things that silently break badges: the yaml losing its real
private-use characters (an editor re-escaping them into ``\\ue200`` text), and
the admin-visible default prompts (platform locales) drifting away from the
rules so the backstop would start double-appending or never firing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bisheng.citation.domain.services.citation_prompt_helper import (
    CITATION_PROMPT_RULES,
    ensure_citation_rules,
    prompt_has_citation_rules,
)

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_CITATION_YAML = _BACKEND_ROOT / "bisheng" / "core" / "prompts" / "yaml" / "citation.yaml"
_LOCALES_DIR = _BACKEND_ROOT.parent / "frontend" / "platform" / "public" / "locales"
_PUA = (chr(0xE200), chr(0xE201), chr(0xE202))


def test_citation_yaml_carries_real_pua_markers_and_no_escaped_form():
    yaml_text = _CITATION_YAML.read_text(encoding="utf-8")
    for marker in _PUA:
        assert marker in yaml_text
        assert marker in CITATION_PROMPT_RULES
    # An editor that re-escapes the file turns the markers into six visible
    # characters; the loaded rules would then teach the model the wrong thing.
    assert "\\" not in yaml_text
    assert "\\" not in CITATION_PROMPT_RULES
    assert not CITATION_PROMPT_RULES.startswith("Failed to load")


def test_citation_rules_take_no_placeholders():
    """Callers format their own prompt first and append the rules verbatim."""
    assert not any(ch in CITATION_PROMPT_RULES for ch in "{}$")


def test_prompt_has_citation_rules_detects_real_and_literal_markers():
    assert prompt_has_citation_rules(f"answer {chr(0xE200)}ks_a:1{chr(0xE202)}")
    assert prompt_has_citation_rules("- `\\ue200`：引用开始标记")
    assert not prompt_has_citation_rules("plain prompt")
    assert not prompt_has_citation_rules("")
    assert not prompt_has_citation_rules(None)


@pytest.mark.parametrize("empty", [None, "", "   \n"])
def test_ensure_citation_rules_returns_rules_alone_for_empty_prompt(empty):
    assert ensure_citation_rules(empty) == CITATION_PROMPT_RULES


def test_ensure_citation_rules_appends_once_to_a_prompt_without_rules():
    custom = "你是某频道的专属助手。\n"
    result = ensure_citation_rules(custom)
    assert result.startswith(custom.rstrip())
    assert result.count(CITATION_PROMPT_RULES) == 1
    assert ensure_citation_rules(result) == result


def test_ensure_citation_rules_leaves_a_prompt_with_literal_markers_untouched():
    """The admin-visible defaults spell the markers as ``\\ue200`` text."""
    visible = "# 引用规则\n- `\\ue200`：引用开始标记"
    assert ensure_citation_rules(visible) == visible


def _locale_prompts():
    for lang in ("zh-Hans", "en-US", "ja"):
        path = _LOCALES_DIR / lang / "bs.json"
        if not path.is_file():
            continue
        chat_config = json.loads(path.read_text(encoding="utf-8-sig")).get("chatConfig", {})
        for key in ("aiPrompt", "systemPrompt2"):
            yield pytest.param(chat_config.get(key, ""), id=f"{lang}:{key}")


@pytest.mark.parametrize("prompt", list(_locale_prompts()))
def test_locale_default_prompts_already_carry_the_rules(prompt):
    """Every admin-editable default template spells the rules itself, so the
    backstop is a no-op on a freshly saved default and never double-appends."""
    if not prompt:
        pytest.skip("platform locales not present in this checkout")
    assert prompt_has_citation_rules(prompt)
    assert ensure_citation_rules(prompt) == prompt
