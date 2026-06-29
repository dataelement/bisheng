"""Unit tests for the deepagents prompt-assembly optimization (F035 follow-up):

1. ``_ensure_linsight_harness_profile`` registers a BiSheng-owned HarnessProfile
   that ONLY sets ``system_prompt_suffix`` (a static Chinese language block) and
   leaves ``base_system_prompt=None`` — so the SDK English BASE is kept and the
   researcher subagent's authored prompt is NOT clobbered (the suffix appends).
   Registration is idempotent per provider and no-ops when no provider derives.
2. The current-time block is injected into the dynamic first user message
   (``_build_agent_input`` / ``_drive_continue``), never the static system
   prompt — so the system prompt stays prefix-cacheable.

Pure-function / lightweight-stub style, mirroring ``test_subagent_reintroduction``.
"""

from __future__ import annotations

import deepagents
from deepagents.profiles.harness.harness_profiles import _get_harness_profile

from bisheng.linsight.domain.services.agent_factory import (
    _LINSIGHT_SYSTEM_PROMPT_SUFFIX_ZH,
    _REGISTERED_SUFFIX_PROVIDERS,
    _ensure_linsight_harness_profile,
)


class _FakeModel:
    """Minimal chat-model stand-in: only ``_get_ls_params`` is consulted by
    deepagents' ``get_model_provider``."""

    def __init__(self, provider: str | None):
        self._provider = provider

    def _get_ls_params(self, *args, **kwargs) -> dict:
        params: dict = {"ls_model_type": "chat"}
        if self._provider is not None:
            params["ls_provider"] = self._provider
        return params


def test_harness_profile_sets_only_suffix_not_base(monkeypatch):
    """The registered profile carries the static Chinese suffix and explicitly
    leaves base_system_prompt None (keeping the SDK BASE, never clobbering the
    researcher subagent which shares this profile)."""
    provider = "bisheng_test_suffix_only"
    _REGISTERED_SUFFIX_PROVIDERS.discard(provider)

    _ensure_linsight_harness_profile(_FakeModel(provider))

    profile = _get_harness_profile(provider)
    assert profile is not None
    assert profile.system_prompt_suffix == _LINSIGHT_SYSTEM_PROMPT_SUFFIX_ZH
    # base slot untouched -> researcher subagent prompt is preserved (append-only)
    assert profile.base_system_prompt is None
    assert provider in _REGISTERED_SUFFIX_PROVIDERS


def test_harness_profile_registration_is_idempotent(monkeypatch):
    """Repeated calls register the provider exactly once (static content; the
    linsight worker builds a fresh agent per task in a long-running process)."""
    provider = "bisheng_test_idempotent"
    _REGISTERED_SUFFIX_PROVIDERS.discard(provider)

    calls: list[str] = []
    orig = deepagents.register_harness_profile

    def _counting(key, profile):
        calls.append(key)
        return orig(key, profile)

    monkeypatch.setattr(deepagents, "register_harness_profile", _counting)

    _ensure_linsight_harness_profile(_FakeModel(provider))
    _ensure_linsight_harness_profile(_FakeModel(provider))

    assert calls == [provider]  # registered once, second call short-circuits


def test_harness_profile_noop_without_provider(monkeypatch):
    """No derivable provider -> no registration (inline language lines fall back)."""
    calls: list[str] = []
    orig = deepagents.register_harness_profile

    def _counting(key, profile):
        calls.append(key)
        return orig(key, profile)

    monkeypatch.setattr(deepagents, "register_harness_profile", _counting)

    _ensure_linsight_harness_profile(_FakeModel(None))

    assert calls == []


def test_assembly_appends_suffix_and_preserves_researcher():
    """Exercise the REAL deepagents prompt-assembly fn with our registered
    profile to prove the central design claims:

    - main agent: USER -> BASE -> SUFFIX, so the English BASE is KEPT and our
      Chinese suffix lands at the very tail.
    - researcher subagent (shares this profile): its authored prompt is
      PRESERVED (suffix appends, base slot is None so nothing is clobbered).
    """
    from deepagents.graph import BASE_AGENT_PROMPT
    from deepagents.profiles.harness.harness_profiles import _apply_profile_prompt

    from bisheng.linsight.domain.services.agent_factory import _build_researcher_prompt

    provider = "bisheng_test_assembly"
    _REGISTERED_SUFFIX_PROVIDERS.discard(provider)
    _ensure_linsight_harness_profile(_FakeModel(provider))
    profile = _get_harness_profile(provider)

    # Main agent base (deepagents passes BASE_AGENT_PROMPT here, graph.py:832).
    main_base = _apply_profile_prompt(profile, BASE_AGENT_PROMPT)
    assert BASE_AGENT_PROMPT in main_base  # SDK English BASE kept
    assert main_base.endswith(_LINSIGHT_SYSTEM_PROMPT_SUFFIX_ZH)  # suffix at tail

    # Researcher subagent base (deepagents passes the spec prompt, graph.py:682).
    researcher_prompt = _build_researcher_prompt(False)
    sub = _apply_profile_prompt(profile, researcher_prompt)
    assert researcher_prompt in sub  # NOT clobbered — append-only
    assert sub.endswith(_LINSIGHT_SYSTEM_PROMPT_SUFFIX_ZH)


def test_suffix_block_constrains_thinking_language():
    """The static suffix must cover thinking and assert top priority over the
    appended English framework prompts (the tail-position language guard)."""
    assert "thinking" in _LINSIGHT_SYSTEM_PROMPT_SUFFIX_ZH
    assert "最高优先级" in _LINSIGHT_SYSTEM_PROMPT_SUFFIX_ZH


class _FakeSession:
    question = "帮我写一份新能源行业研究报告"


def test_current_time_block_format():
    from bisheng.linsight.domain.task_exec import LinsightWorkflowTask

    block = LinsightWorkflowTask._current_time_block()
    assert block.startswith("# 当前时间")
    assert "周" in block  # weekday rendered


def test_build_agent_input_includes_time_and_question():
    from bisheng.linsight.domain.task_exec import LinsightWorkflowTask

    out = LinsightWorkflowTask._build_agent_input(_FakeSession(), file_list=None)
    content = out["messages"][0]["content"]
    assert "# 当前时间" in content
    assert _FakeSession.question in content
