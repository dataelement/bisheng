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

Two steps used to be missing and were held here as ``xfail(strict=True)``
sentinels: the pack taught no local way to follow an approval, and the
access-information text an administrator hands over did not exist. T041 and
T046 landed both, so those sentinels are now ordinary assertions — and the
assertions check the *content*, not merely its presence, because an exit code
or a tool name taught wrongly is worse than one never taught.

What still needs a real platform and a real machine (reported, not faked):
handing a key over, ``bisheng login`` against it, one live MCP tool call, and
an administrator actually approving the release.
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


SRC_ROOT = Path(__file__).resolve().parents[3]
PLATFORM_SRC = SRC_ROOT / "frontend" / "platform" / "src"
SERVICE_ACCOUNT_DIR = PLATFORM_SRC / "pages" / "SystemPage" / "components" / "ServiceAccount"
CLI_EXIT_CODES = SRC_ROOT / "bisheng-cli" / "bisheng_cli" / "errors.py"


class TestJourneyLastStepApprovalTracking:
    """AC-47's final link, closed by T041.

    The pack used to end at "wait for an administrator to approve it", which is
    where an agent has to send the developer to a web page — the one thing AC-47
    says must not happen. Both local ways of following an approval now exist and
    both are taught; these tests keep them taught *and correct*, because an exit
    code or a tool name that drifts is worse than one that was never written.
    """

    def test_the_pack_teaches_both_local_ways_to_follow_an_approval(self, skill_text):
        assert "bisheng deploy . --wait" in skill_text
        assert "--wait-timeout" in skill_text
        assert "bisheng_app_status" in skill_text

    def test_the_exit_codes_it_teaches_are_the_codes_the_cli_actually_returns(self, skill_text):
        """Read off `errors.py`, not remembered — a renumbering must break here.

        The pack is the agent's whole model of "what does this exit code mean";
        teaching 20 as "rejected" while the CLI returns something else sends it
        to fix a rejection that did not happen.
        """
        source = CLI_EXIT_CODES.read_text(encoding="utf-8")
        for name, taught in (
            ("EXIT_REJECTED", 20),
            ("EXIT_WITHDRAWN", 21),
            ("EXIT_PENDING_ONLINE", 22),
            ("EXIT_WAIT_TIMEOUT", 23),
        ):
            assert f"{name} = {taught}" in source, f"{name} is no longer {taught}"
            assert f"| {taught} |" in skill_text, f"exit code {taught} lost its row in the pack"

    def test_the_status_tool_it_names_is_a_real_tool_with_that_scope(self, skill_text):
        """`app:manage` is what the pack tells the developer to ask their admin for."""
        from bisheng.open_api.mcp.registry import TOOLS_BY_NAME

        spec = TOOLS_BY_NAME.get("bisheng_app_status")
        assert spec is not None, "the pack names an MCP tool the face does not serve"
        assert spec.scope == "app:manage"
        assert "app:manage" in skill_text

    def test_it_does_not_confuse_logs_with_approval_state(self, skill_text):
        # The most likely wrong move once `logs` is in the same section.
        assert "不是**审批状态" in skill_text


class TestAccessInfoAnAdministratorCanHandOver:
    """AC-46's input, landed by T046 — the journey's first step has a source.

    The developer's half of AC-46 (login, then one MCP call) needs a machine;
    what can be pinned here is that the text they are handed exists, names all
    four things, and carries no key.
    """

    @pytest.fixture(scope="class")
    def panel_source(self) -> str:
        return "\n".join(path.read_text(encoding="utf-8") for path in SERVICE_ACCOUNT_DIR.rglob("*.tsx"))

    def test_the_panel_reads_the_addresses_from_the_platform(self, panel_source):
        assert "dev-toolkit" in panel_source or "getDevToolkitVersionsApi" in panel_source

    def test_it_covers_all_four_items_the_developer_needs(self, panel_source):
        for key in ("mcpAddress", "modelBaseUrl", "cliDownload", "loginCommand", "platformAddress"):
            assert f"accessInfo.{key}" in panel_source, f"the access-information block lost {key}"
        assert "bisheng login" in panel_source

    def test_the_copied_text_carries_no_credential(self, panel_source):
        """AC-45, checked where it can actually rot: the component's own source.

        The key is represented by a placeholder key, and nothing in the block
        ever reads an issued key — `KeyRevealDialog` is the one place plaintext
        exists, and it is a different component.
        """
        panel = (SERVICE_ACCOUNT_DIR / "AccessInfoPanel.tsx").read_text(encoding="utf-8")
        assert "accessInfo.keyPlaceholder" in panel
        for forbidden in ("plaintext", "bs-sak-", "Authorization", "issuedKey"):
            assert forbidden not in panel, f"the access-information block references {forbidden}"
