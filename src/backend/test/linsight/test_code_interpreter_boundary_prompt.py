"""Execution-boundary wording for the code interpreter.

Users ask task mode to print env vars or "the keys in the config". These tests pin:

  * both executor tool descriptions carry the shared boundary rules;
  * the linsight system prompt carries its Chinese twin IFF a code interpreter
    is bound (prompt <-> tool lockstep, like the path-namespace section);
  * no model-facing text explains WHY the boundary exists — the model repeats
    these strings to the user, and "shared infrastructure / other users' data /
    backend environment" would only advertise where to look.

Wording only: this lowers how often the model tries; it is not access control.
"""

from __future__ import annotations

import pytest

from bisheng.linsight.domain.services.agent_factory import _build_linsight_system_prompt
from bisheng_langchain.gpts.tools.code_interpreter.base_executor import (
    EXECUTION_BOUNDARY_RULES,
    WORKSPACE_ESCAPE_NOTICE,
)
from bisheng_langchain.gpts.tools.code_interpreter.e2b_executor import E2bCodeExecutor
from bisheng_langchain.gpts.tools.code_interpreter.local_executor import LOCAL_DESCRIPTION

PROMPT_BOUNDARY_HEADING = "# 执行环境边界"

# Phrases that disclose where platform data lives or that the run shares a host.
REVEALING_PHRASES = ("shared infrastructure", "other users", "backend python environment", "shared, offline")


def _e2b_description() -> str:
    # description only reads module constants; skip __init__ (it would build a sandbox)
    return E2bCodeExecutor.description.fget(object.__new__(E2bCodeExecutor))


def test_local_description_carries_boundary_rules():
    assert EXECUTION_BOUNDARY_RULES in LOCAL_DESCRIPTION


def test_e2b_description_carries_boundary_rules():
    assert EXECUTION_BOUNDARY_RULES in _e2b_description()


def test_boundary_rules_keep_user_uploads_readable():
    # A user analysing their own uploaded .env is a legitimate task, not a probe.
    assert "uploads/" in EXECUTION_BOUNDARY_RULES
    assert ".env" in EXECUTION_BOUNDARY_RULES


@pytest.mark.parametrize("text_name", ["LOCAL_DESCRIPTION", "E2B_DESCRIPTION", "WORKSPACE_ESCAPE_NOTICE", "RULES"])
def test_model_facing_text_does_not_explain_where_data_lives(text_name):
    text = {
        "LOCAL_DESCRIPTION": LOCAL_DESCRIPTION,
        "E2B_DESCRIPTION": _e2b_description(),
        "WORKSPACE_ESCAPE_NOTICE": WORKSPACE_ESCAPE_NOTICE,
        "RULES": EXECUTION_BOUNDARY_RULES,
    }[text_name].lower()
    for phrase in REVEALING_PHRASES:
        assert phrase not in text, f"{text_name} contains {phrase!r}"


@pytest.mark.parametrize("has_kb", [True, False])
def test_prompt_boundary_section_present_with_code_interpreter(has_kb):
    prompt = _build_linsight_system_prompt(has_kb, has_code_interpreter=True)
    assert PROMPT_BOUNDARY_HEADING in prompt
    assert "os.environ" in prompt
    assert "uploads/" in prompt


@pytest.mark.parametrize("has_kb", [True, False])
def test_prompt_boundary_section_absent_without_code_interpreter(has_kb):
    # lockstep: never name bisheng_code_interpreter when it is not bound
    prompt = _build_linsight_system_prompt(has_kb, has_code_interpreter=False)
    assert PROMPT_BOUNDARY_HEADING not in prompt


def test_prompt_boundary_section_survives_unattended_mode():
    prompt = _build_linsight_system_prompt(True, has_code_interpreter=True, unattended=True)
    assert PROMPT_BOUNDARY_HEADING in prompt
