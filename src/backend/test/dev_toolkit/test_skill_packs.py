"""F053 T037 / T038 — the developer skill packs ship intact and self-check readably.

A pack is guidance an external AI coding tool follows to build a deployable
app, so the things that must hold are structural (AC-18): the three pieces are
present, the example carries no real secret and validates against the manifest
schema it teaches, and the self-check fails with a sentence rather than a
traceback when the developer has not logged in yet. Those hold for every pack;
the second half of this file pins what is specific to「平台能力接线」(AC-17):
the auth chapter is first and opens with the silent-failure warning, the
header names it teaches are app-proxy's, and the model chapter says 暂未提供
instead of inventing an endpoint.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from bisheng.dev_toolkit.domain.services.artifact_service import SKILLS_DIR

PACKS = ("deploy-hosting", "platform-wiring")

# F049's scan rule for a real service-account key. A pack must never carry one.
_KEY_RE = re.compile(r"\bbs-sak-[A-Za-z0-9_-]{43}\b")

# `bisheng dev` and app-proxy inject these; the pack must teach exactly these
# names. Read from app-proxy's source rather than imported: the backend does
# not depend on app-proxy, and the names are literals in that file.
_APP_PROXY_HEADERS = Path(__file__).resolve().parents[3] / "app-proxy" / "app_proxy" / "headers.py"


def _pack(name: str) -> Path:
    return SKILLS_DIR / name


def _frontmatter(pack: Path) -> str:
    text = (pack / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---")
    return text.split("---", 2)[1]


@pytest.mark.parametrize("name", PACKS)
def test_pack_has_the_three_pieces(name: str):
    # SKILL.md + runnable example + self-check script (AC-18).
    pack = _pack(name)
    assert (pack / "SKILL.md").is_file()
    assert (pack / "example" / "main.py").is_file()
    assert (pack / "example" / "bisheng-app.yaml").is_file()
    assert (pack / "selfcheck.py").is_file()


@pytest.mark.parametrize("name", PACKS)
def test_skill_md_frontmatter_name_matches_dir(name: str):
    front = _frontmatter(_pack(name))
    assert re.search(rf"^name:\s*{re.escape(name)}\s*$", front, re.MULTILINE)
    assert re.search(r"^\s*display-name:\s*\S", front, re.MULTILINE)


@pytest.mark.parametrize("name", PACKS)
def test_no_real_secret_anywhere_in_the_pack(name: str):
    for path in _pack(name).rglob("*"):
        if path.is_file():
            body = path.read_text(encoding="utf-8", errors="ignore")
            assert not _KEY_RE.search(body), f"real key literal in {path}"


@pytest.mark.parametrize("name", PACKS)
def test_example_manifest_is_valid_against_the_platform_schema(name: str):
    # The example must itself pass the manifest schema it teaches — unknown keys
    # or a missing required field would mean the pack tells developers to write
    # something the platform's ``extra='forbid'`` schema rejects. Checked against
    # the pure schema (no DB tier resolution needed).
    import yaml

    from bisheng.app_publish.domain.schemas.app_manifest import SUPPORTED_RUNTIMES, AppManifest

    raw = (_pack(name) / "example" / "bisheng-app.yaml").read_text(encoding="utf-8")
    manifest = AppManifest(**yaml.safe_load(raw))  # raises on unknown/missing fields
    assert manifest.runtime in SUPPORTED_RUNTIMES
    assert manifest.name
    assert manifest.capabilities.is_empty()  # capabilities must be empty this round


@pytest.mark.parametrize("name", PACKS)
def test_example_is_stdlib_only(name: str):
    # An empty requirements file is the contract both packs teach: the build
    # never has to reach PyPI.
    requirements = (_pack(name) / "example" / "requirements.txt").read_text(encoding="utf-8")
    assert not [line for line in requirements.splitlines() if line.strip() and not line.startswith("#")]


@pytest.mark.parametrize("name", PACKS)
def test_selfcheck_reports_readable_reason_when_not_logged_in(name: str, tmp_path):
    # AC-18: missing config → a readable failure, never a stack trace. Run it with
    # a fresh HOME so there is no credentials file.
    home = tmp_path / "home"
    home.mkdir()
    result = subprocess.run(
        [sys.executable, str(_pack(name) / "selfcheck.py")],
        capture_output=True,
        text=True,
        env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
    )
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "未登录" in combined or "凭据" in combined
    assert "Traceback" not in combined


# ---- platform-wiring specifics (AC-17) ----------------------------------------


WIRING = _pack("platform-wiring")


def _chapters(text: str) -> list[tuple[str, str]]:
    """`(heading, body)` for every `## ` chapter, in order."""
    parts = re.split(r"^## ", text, flags=re.MULTILINE)[1:]
    return [(part.split("\n", 1)[0].strip(), part.split("\n", 1)[1] if "\n" in part else "") for part in parts]


def test_auth_chapter_is_first_in_toc_and_in_the_body_and_opens_with_the_warning():
    text = (WIRING / "SKILL.md").read_text(encoding="utf-8")
    body = text.split("---", 2)[2]
    # TOC: the first numbered entry is the identity chapter.
    toc_first = re.search(r"^1\. \[([^\]]+)\]", body, re.MULTILINE)
    assert toc_first and "身份" in toc_first.group(1)
    # Body: the first chapter is the identity chapter and starts with a warning block.
    chapters = _chapters(body)
    heading, content = chapters[0]
    assert "身份" in heading
    first_para = content.strip().split("\n\n", 1)[0]
    assert first_para.startswith(">") and "⚠️" in first_para and "静默" in first_para
    # The warning names the failure point: building your own login.
    assert "登录页" in first_para


def test_auth_chapter_teaches_exactly_app_proxys_header_names():
    source = _APP_PROXY_HEADERS.read_text(encoding="utf-8")
    block = re.search(r"INJECTED_HEADER_NAMES[^=]*=\s*\((.*?)\)", source, re.DOTALL)
    assert block, "app-proxy no longer declares INJECTED_HEADER_NAMES — the pack's header table must be re-checked"
    injected = set(re.findall(r'"(X-BiSheng-[A-Za-z-]+)"', block.group(1)))
    taught = set(re.findall(r"`(X-BiSheng-[A-Za-z-]+)`", (WIRING / "SKILL.md").read_text(encoding="utf-8")))
    # Every taught name is a real one, and every real one is taught.
    assert taught == injected, f"pack/app-proxy header drift: {taught ^ injected}"
    # The access-token handle now has exactly one consumer — the SDK's retrieve —
    # and the row must still forbid the app doing anything with it itself
    # (parsing it, storing it, treating it as a permission). F057 changed the
    # contract; this guard changed with it, in the same PR.
    text = (WIRING / "SKILL.md").read_text(encoding="utf-8")
    token_row = next(line for line in text.splitlines() if line.startswith("| `X-BiSheng-Access-Token`"))
    assert "不要自己解析" in token_row


def test_model_chapter_is_marked_not_yet_available_and_invents_no_endpoint():
    body = (WIRING / "SKILL.md").read_text(encoding="utf-8").split("---", 2)[2]
    model = next((content for heading, content in _chapters(body) if "模型" in heading), None)
    assert model is not None
    assert "暂未提供" in model
    # No URL at all in that chapter: nothing to copy-paste into a client.
    assert not re.search(r"https?://", model)
    assert "不要猜" in model


def test_app_db_chapter_uses_the_injected_env_names_and_stdlib_sqlite3():
    text = (WIRING / "SKILL.md").read_text(encoding="utf-8")
    example = (WIRING / "example" / "main.py").read_text(encoding="utf-8")
    for name in ("BISHENG_APP_DB_PATH", "BISHENG_APP_DB_URL"):
        assert name in text
    assert "BISHENG_APP_DB_PATH" in example and "import sqlite3" in example
    assert "CREATE TABLE IF NOT EXISTS" in example and "ensure_column" in example
    # The schema-evolution policy is stated honestly: the confirmation is
    # recorded, not enforced, this round.
    assert "--confirm-schema-change" in text and "只**记录**" in text


def test_example_reads_identity_from_headers_and_has_no_login():
    example = (WIRING / "example" / "main.py").read_text(encoding="utf-8")
    assert "X-BiSheng-User-Id" in example and "unquote" in example
    for forbidden in ("password", "login", "jwt", "set-cookie"):
        assert forbidden not in example.lower(), f"the example must not roll its own auth ({forbidden})"
