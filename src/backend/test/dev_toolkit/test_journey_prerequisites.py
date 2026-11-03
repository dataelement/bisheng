"""Published deployment guidance matches the 130 hosted-app manifest contract.

Standalone CLI approval tracking, Open MCP and the credential handover panel
are not shipped by this desktop-account port; their source-freeze assertions
belong to those features. Actual desktop approval/progress is covered by the
cloud-workbench service suite and the local end-to-end evidence.
"""

from __future__ import annotations

import re

import pytest

from bisheng.dev_toolkit.domain.services.artifact_service import SKILLS_DIR

SKILL_MD = SKILLS_DIR / "deploy-hosting" / "SKILL.md"


@pytest.fixture(scope="module")
def skill_text() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


class TestJourneyStepsTheSkillPackTeaches:
    """AC-47's chain, as far as the pack takes it."""

    def test_step_one_login_with_a_handed_over_key(self, skill_text):
        # AC-46's local half: the pack tells the agent the exact command and
        # that the key arrives separately, from an administrator.
        assert "bisheng login <平台地址> --api-key bs-sak-" in skill_text
        assert "--api-key-stdin" in skill_text

    def test_step_two_declaration_completion(self, skill_text):
        # The manifest is what "补全应用包声明" means; name and runtime are the
        # required pair, and the pack has to say which keys exist at all.
        assert "bisheng-app.yaml" in skill_text
        for key in ("manifest_version:", "name:", "runtime:", "port:", "slug:", "tier:"):
            assert key in skill_text, f"manifest key {key} is not documented"
        # The keys that do *not* exist matter as much: the manifest rejects
        # unknown fields outright, so an agent inventing `command:` gets 16221
        # rather than a default.
        assert "没有 `health` / `command` / `entry` / `start` 这些字段" in skill_text

    def test_step_three_deploy(self, skill_text):
        assert "bisheng deploy ." in skill_text
        assert "--dry-run" in skill_text

    def test_step_four_precheck_codes_match_the_backend(self, skill_text):
        """Every precheck code the pack teaches must exist, with that meaning.

        The pack's troubleshooting table is the agent's entire model of "what
        went wrong and what to do". A code that no longer exists sends it to fix
        the wrong thing; a code the backend raises and the pack omits leaves it
        with no move at all. Both directions are checked over the precheck +
        secret-scan bands, which are the ones a `deploy` can actually return to
        a developer.
        """
        from bisheng.common.errcode import app_publish as errcodes

        documented = {int(code) for code in re.findall(r"\b(162[2-4]\d)\b", skill_text)}
        defined = {
            value.Code
            for value in vars(errcodes).values()
            if isinstance(value, type) and isinstance(getattr(value, "Code", None), int)
        }
        precheck_band = {code for code in defined if 16220 <= code <= 16249}

        assert documented, "the troubleshooting table lost its error codes"
        unknown = documented - defined
        assert unknown == set(), f"the pack teaches codes the backend never raises: {sorted(unknown)}"

        # Codes a developer cannot act on are deliberately absent: 16223 (tier
        # misconfigured) and 16225 (the approval scenario is not seeded) are
        # administrator problems, and 16227 / 16224 are internal pipeline
        # states. Everything else in the band has to be teachable.
        administrator_only = {16223, 16224, 16225, 16227}
        missing = precheck_band - documented - administrator_only
        assert missing == set(), f"precheck codes with no entry in the pack's table: {sorted(missing)}"

    def test_it_says_deploy_success_is_not_yet_online(self, skill_text):
        # The single most common misreading of a green `deploy`. The pack has to
        # say it before it can say how to follow the approval.
        assert "部署成功不等于上线" in skill_text
