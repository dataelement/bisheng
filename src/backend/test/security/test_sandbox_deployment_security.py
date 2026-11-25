"""Offline deployment contract checks, no Docker or network calls."""

import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[4]


@pytest.mark.parametrize("initial", ["", "bisheng-sandbox-local", "short", "a" * 64])
def test_installer_token_is_private_idempotent_and_not_printed(tmp_path, initial):
    target = tmp_path / ".env"
    target.write_text("SANDBOX_TOKEN=" + initial + "\n")
    script = 'source "$ROOT/docker/lib/install-env.sh"; source "$ROOT/docker/lib/sandbox-security.sh"; die(){ exit 3; }; sandbox_initialize_token; sandbox_initialize_token'
    result = subprocess.run(
        ["bash", "-c", script],
        env={**os.environ, "ROOT": str(ROOT), "SCRIPT_DIR": str(ROOT / "docker"), "ENV_FILE": str(target)},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    value = target.read_text().split("=", 1)[1].strip().strip("'\"")
    assert len(value) == 64
    if len(initial) == 64:
        assert value == initial
    else:
        assert value != initial
    assert value not in result.stdout + result.stderr


def test_compose_control_token_required_and_middleware_ports_local():
    data = yaml.safe_load((ROOT / "docker/docker-compose.yml").read_text())
    for name in ("backend", "backend_worker", "code-runner-1", "code-runner-2"):
        environment = data["services"][name]["environment"]
        field = "SANDBOX_TOKEN" if name.startswith("code-runner") else "BS_SANDBOX_CONF__TOKEN"
        assert "SANDBOX_TOKEN:?" in environment[field]
        assert "bisheng-sandbox-local" not in environment[field]
    for name in ("mysql", "redis", "openfga", "elasticsearch", "milvus", "minio"):
        assert all("127.0.0.1" in port for port in data["services"][name]["ports"])
    assert "7860:7860" in data["services"]["backend"]["ports"]
    assert "3001:3001" in data["services"]["frontend"]["ports"]
