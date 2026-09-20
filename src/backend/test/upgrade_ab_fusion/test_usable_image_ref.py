"""REPLACE 占位不能当镜像 pull/graft."""

from __future__ import annotations

import os
import subprocess

from test.upgrade_ab_fusion._packutil import ensure_pack_path

PACK = ensure_pack_path()
COMMON = PACK / "lib" / "common.sh"


def _ok(img: str) -> bool:
    env = os.environ.copy()
    proc = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; if usable_image_ref "$2"; then echo yes; else echo no; fi',
            "_",
            str(COMMON),
            img,
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return proc.stdout.strip().splitlines()[-1] == "yes"


def test_rejects_placeholders():
    assert not _ok("")
    assert not _ok("REPLACE_WITH_PINNED_OPENFGA_DIGEST")
    assert not _ok("registry.example.com/x@sha256:REPLACE")


def test_accepts_real_refs():
    assert _ok("openfga/openfga:v1.8.12")
    assert _ok("openfga/openfga:latest")
    assert _ok("cr.example.com/openfga@sha256:" + ("a" * 64))
