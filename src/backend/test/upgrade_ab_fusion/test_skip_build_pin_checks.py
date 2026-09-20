"""没填 40 位 sha 时跳过钉扎, 不必再 export DRILL=1."""

from __future__ import annotations

import os
import subprocess

from test.upgrade_ab_fusion._packutil import ensure_pack_path

PACK = ensure_pack_path()
COMMON = PACK / "lib" / "common.sh"


def _result(commit: str, drill: str = "0") -> str:
    env = os.environ.copy()
    env["TARGET_GIT_COMMIT"] = commit
    env["DRILL"] = drill
    proc = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; skip_build_pin_checks && echo skip || echo pin',
            "_",
            str(COMMON),
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    lines = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
    return lines[-1]


def test_placeholder_skips_without_drill():
    assert _result("DRILL-SKIP") == "skip"
    assert _result("REPLACE_WITH_40_CHAR_SHA") == "skip"


def test_real_sha_pins_unless_drill():
    sha = "a" * 40
    assert _result(sha) == "pin"
    assert _result(sha, drill="1") == "skip"
