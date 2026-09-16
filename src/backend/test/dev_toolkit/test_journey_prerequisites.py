"""F053 T041 (checkable half) — what the cross-Feature journey needs locally.

T041 itself is an end-to-end run on a real platform: a key is handed over, the
developer runs ``bisheng login``, calls an MCP tool, and their coding agent
carries an application from declaration to an approved release without leaving
the local conversation (AC-46, AC-47). That run needs F052's MCP face and a
machine; it cannot happen here.

What *can* be pinned here is the journey's local prerequisites — the material
the agent actually reads and the error codes it is told to act on. Those are the
parts that rot silently: a precheck code renamed in the backend leaves the skill
pack telling the agent to fix something the platform never reports, and nothing
fails until a developer is stuck.

The two steps that are **not** satisfied today are marked ``xfail(strict=True)``
rather than described in prose, so they turn red on the day they land.
"""

from __future__ import annotations

import re
from pathlib import Path

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


class TestJourneyGapsNotYetClosed:
    @pytest.mark.xfail(
        strict=True,
        reason=(
            "AC-47 last step: the pack tells the agent to wait for an approval "
            "but never how to follow it from the local conversation. "
            "`bisheng deploy --wait` exists in the CLI and the MCP status tool "
            "is F052's; neither is mentioned. Delete this sentinel once the "
            "pack teaches one of them."
        ),
    )
    def test_approval_tracking_is_teachable_without_leaving_the_terminal(self, skill_text):
        assert "--wait" in skill_text or "应用状态" in skill_text

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "AC-46 input: the service-account detail page's 接入信息区 and its "
            "one-click copy (F053 AC-44 / AC-45, task T046) are not built, so "
            "there is no access-info text for an administrator to hand over. "
            "Delete this sentinel when T046 lands."
        ),
    )
    def test_access_info_text_exists_for_an_administrator_to_copy(self):
        platform_src = Path(__file__).resolve().parents[3] / "frontend" / "platform" / "src"
        service_account = platform_src / "pages" / "SystemPage" / "components" / "ServiceAccount"
        sources = "\n".join(path.read_text(encoding="utf-8") for path in service_account.rglob("*.tsx"))
        assert "dev-toolkit" in sources
