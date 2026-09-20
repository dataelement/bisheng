"""2.5 hop 从 compose service 块读 image, 不覆盖成脚本默认 tag."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from test.upgrade_ab_fusion._packutil import ensure_pack_path

PACK = ensure_pack_path()
REPLACE = PACK / "lib" / "replace_configs.sh"


def _image(compose: Path, service: str) -> str:
    env = os.environ.copy()
    env["COMPOSE_FILE"] = str(compose)
    proc = subprocess.run(
        [
            "bash",
            "-c",
            'die() { echo "FAIL: $*" >&2; exit 1; }; source "$1"; compose_service_image "$2"',
            "_",
            str(REPLACE),
            service,
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return proc.stdout.strip().splitlines()[-1]


def test_reads_backend_and_frontend(tmp_path: Path):
    compose = tmp_path / "docker-compose.yml"
    compose.write_text(
        "services:\n"
        "  backend:\n"
        "    container_name: bisheng-backend\n"
        "    image: 10.171.0.14:21020/skm-images/bisheng-backend-shougang:v2.5.0-amd64-test\n"
        "    ports:\n"
        '      - "7860:7860"\n'
        "  frontend:\n"
        "    image: 10.171.0.14:21020/skm-images/bisheng-frontend-shougang:v2.5.0-amd64-test\n"
        "  openfga:\n"
        "    image: openfga/openfga:latest\n",
        encoding="utf-8",
    )
    assert _image(compose, "backend").endswith("bisheng-backend-shougang:v2.5.0-amd64-test")
    assert _image(compose, "frontend").endswith("bisheng-frontend-shougang:v2.5.0-amd64-test")
    assert _image(compose, "openfga") == "openfga/openfga:latest"


def test_does_not_use_sibling_service_image(tmp_path: Path):
    compose = tmp_path / "docker-compose.yml"
    compose.write_text(
        "services:\n  mysql:\n    image: mysql:8.0\n  backend:\n    image: registry.example.com/bisheng-backend:prod\n",
        encoding="utf-8",
    )
    assert _image(compose, "backend") == "registry.example.com/bisheng-backend:prod"
