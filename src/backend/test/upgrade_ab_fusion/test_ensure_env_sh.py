"""缺 env.sh 时从 example 生成, 已有则不覆盖."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

from test.upgrade_ab_fusion._packutil import ensure_pack_path

PACK = ensure_pack_path()
COMMON = PACK / "lib" / "common.sh"


def _run_ensure(pack: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PACK_ROOT"] = str(pack)
    return subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; if ensure_env_sh; then echo rc=0; else echo rc=1; fi; '
            'if [[ -f "$PACK_ROOT/env.sh" ]]; then echo has; else echo missing; fi',
            "_",
            str(COMMON),
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )


def test_creates_from_example(tmp_path: Path):
    pack = tmp_path / "pack"
    pack.mkdir()
    (pack / "env.sh.example").write_text("export A_SSH_HOST=''\n", encoding="utf-8")
    proc = _run_ensure(pack)
    assert "rc=0" in proc.stdout
    assert "has" in proc.stdout
    envf = pack / "env.sh"
    assert envf.read_text(encoding="utf-8") == "export A_SSH_HOST=''\n"
    assert stat.S_IMODE(envf.stat().st_mode) == 0o600


def test_does_not_overwrite_existing(tmp_path: Path):
    pack = tmp_path / "pack"
    pack.mkdir()
    (pack / "env.sh.example").write_text("NEW\n", encoding="utf-8")
    (pack / "env.sh").write_text("KEEP\n", encoding="utf-8")
    proc = _run_ensure(pack)
    assert "rc=0" in proc.stdout
    assert (pack / "env.sh").read_text(encoding="utf-8") == "KEEP\n"


def test_missing_example_returns_nonzero(tmp_path: Path):
    pack = tmp_path / "pack"
    pack.mkdir()
    proc = _run_ensure(pack)
    assert "rc=1" in proc.stdout
    assert "missing" in proc.stdout
    assert not (pack / "env.sh").exists()
