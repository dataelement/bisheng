"""F053 T037 — the「部署纳管」developer skill pack ships intact and self-checks readably.

The pack is guidance an external AI coding tool follows to build a deployable
app, so the things that must hold are structural (AC-18): the three pieces are
present, the example carries no real secret, and the self-check fails with a
sentence rather than a traceback when the developer has not logged in yet.
"""

from __future__ import annotations

import re
import subprocess
import sys

from bisheng.dev_toolkit.domain.services.artifact_service import SKILLS_DIR

PACK = SKILLS_DIR / "deploy-hosting"

# F049's scan rule for a real service-account key. A pack must never carry one.
_KEY_RE = re.compile(r"\bbs-sak-[A-Za-z0-9_-]{43}\b")


def test_pack_has_the_three_pieces():
    # SKILL.md + runnable example + self-check script (AC-18).
    assert (PACK / "SKILL.md").is_file()
    assert (PACK / "example" / "main.py").is_file()
    assert (PACK / "example" / "bisheng-app.yaml").is_file()
    assert (PACK / "selfcheck.py").is_file()


def test_skill_md_frontmatter_name_matches_dir():
    text = (PACK / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---")
    front = text.split("---", 2)[1]
    assert re.search(r"^name:\s*deploy-hosting\s*$", front, re.MULTILINE)


def test_no_real_secret_anywhere_in_the_pack():
    for path in PACK.rglob("*"):
        if path.is_file():
            body = path.read_text(encoding="utf-8", errors="ignore")
            assert not _KEY_RE.search(body), f"real key literal in {path}"


def test_example_manifest_is_valid_against_the_platform_schema():
    # The example must itself pass the manifest schema it teaches — unknown keys
    # or a missing required field would mean the pack tells developers to write
    # something the platform's ``extra='forbid'`` schema rejects. Checked against
    # the pure schema (no DB tier resolution needed).
    import yaml

    from bisheng.app_publish.domain.schemas.app_manifest import SUPPORTED_RUNTIMES, AppManifest

    raw = (PACK / "example" / "bisheng-app.yaml").read_text(encoding="utf-8")
    manifest = AppManifest(**yaml.safe_load(raw))  # raises on unknown/missing fields
    assert manifest.runtime in SUPPORTED_RUNTIMES
    assert manifest.name
    assert manifest.capabilities.is_empty()  # capabilities must be empty this round


def test_selfcheck_reports_readable_reason_when_not_logged_in(tmp_path):
    # AC-18: missing config → a readable failure, never a stack trace. Run it with
    # a fresh HOME so there is no credentials file.
    home = tmp_path / "home"
    home.mkdir()
    result = subprocess.run(
        [sys.executable, str(PACK / "selfcheck.py")],
        capture_output=True,
        text=True,
        env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
    )
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "未登录" in combined or "凭据" in combined
    assert "Traceback" not in combined
