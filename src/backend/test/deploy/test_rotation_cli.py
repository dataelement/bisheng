"""覆盖 AC: AC-50, AC-51, AC-54, AC-56 — installer tool contract."""

import subprocess
from pathlib import Path

from bisheng.core.config.credential_tool import main
from test.core.test_credential_rotation import rotation_deployment as rotation_deployment


def test_capability_needs_no_key_or_server(capsys):
    assert main(["rotation", "capabilities"]) == 0
    assert capsys.readouterr().out.strip() == "rotation-v1"


def test_milvus_exception_keeps_normal_batch_preflight(rotation_deployment, monkeypatch, capsys):
    from bisheng.core.config import credential_rotation_native as native

    create, _, key, _ = rotation_deployment
    session = create(("mysql", "milvus"))
    before = (session / "journal.json").read_bytes()
    contacted = []
    monkeypatch.setattr(native, "preflight_identities", lambda *a, **k: contacted.append(True))
    assert main(["rotation", "preflight", "--session-dir", str(session), "--key-file", str(key)]) == 0
    assert contacted == [True]
    assert (session / "journal.json").read_bytes() == before
    assert "all selected identities verified" in capsys.readouterr().out


def test_prepare_and_read_resume_plan(rotation_deployment, capsys):
    create, _, key, _ = rotation_deployment
    session = create(("redis",))
    assert main(["rotation", "info", "--session-dir", str(session), "--key-file", str(key), "--field", "selected"]) == 0
    assert capsys.readouterr().out.strip() == "redis"
    assert main(["rotation", "mark", "--session-dir", str(session), "--key-file", str(key), "--phase", "COMPLETE"]) == 2
    assert "cannot be skipped" in capsys.readouterr().err


def test_native_sdk_failure_is_redacted(rotation_deployment, monkeypatch, capsys):
    from bisheng.core.config import credential_rotation_cli

    create, _, key, _ = rotation_deployment
    session = create(("redis",))

    def unsafe(args):
        raise RuntimeError("server-error-with-secret-SHOULD-NOT-PRINT")

    monkeypatch.setattr(credential_rotation_cli, "execute", unsafe)
    assert (
        main(
            [
                "rotation",
                "step",
                "--session-dir",
                str(session),
                "--key-file",
                str(key),
                "--component",
                "redis",
                "--apply",
            ]
        )
        == 3
    )
    output = capsys.readouterr()
    assert "SHOULD-NOT-PRINT" not in output.out + output.err
    assert "preserve the plan" in output.err


def test_wrapper_requires_explicit_network_before_docker():
    root = Path(__file__).resolve().parents[4]
    result = subprocess.run(
        ["bash", str(root / "docker/credentials.sh"), "--image", "unused", "rotation", "step"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "explicit --network" in result.stderr


def test_capture_refuses_foreign_or_ambiguous_dns_before_native_management(rotation_deployment, monkeypatch):
    import socket

    import pytest

    from bisheng.core.config.credential_rotation_cli import validate_owned_endpoints
    from bisheng.core.config.credential_tool import check_bundle
    from bisheng.core.config.secret_crypto import CredentialConfigurationError

    _, base, _, env = rotation_deployment
    settings = check_bundle(base, env_file=env)[0]
    inventory = {
        "compose": {"services": {"mysql": {"container_name": "managed-mysql"}}},
        "containers": [
            {
                "Config": {"Labels": {"com.docker.compose.service": "mysql"}},
                "NetworkSettings": {"Networks": {"default": {"IPAddress": "172.30.0.2"}}},
            }
        ],
    }
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("172.30.0.2", 0))]
    )
    validate_owned_endpoints(settings, ["mysql"], inventory)
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("172.30.0.3", 0))]
    )
    with pytest.raises(CredentialConfigurationError, match="outside the captured"):
        validate_owned_endpoints(settings, ["mysql"], inventory)
