"""Exercise the host wrapper with a Docker boundary double, without host Python."""

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]


@pytest.mark.parametrize("output_first", [False, True])
def test_wrapper_shared_input_output_parent_has_one_writable_mount(tmp_path, output_first):
    fake = tmp_path / "docker"
    log = tmp_path / "args"
    fake.write_text('#!/bin/sh\nprintf "%s\\n" "$@" >> "$CAPTURE"\n')
    fake.chmod(0o700)
    inputs = tmp_path / "inputs.yaml"
    inputs.write_text("version: 1\n")
    groups = [["--inputs", str(inputs)], ["--out-dir", str(tmp_path / "bundle")]]
    if output_first:
        groups.reverse()
    result = subprocess.run(
        [
            "bash",
            str(ROOT / "docker/credentials.sh"),
            "--image",
            "local:test",
            "prepare",
            *[arg for group in groups for arg in group],
        ],
        env={**os.environ, "PATH": f"{tmp_path}:/usr/bin:/bin", "CAPTURE": str(log)},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    specs = [line for line in log.read_text().splitlines() if line.startswith("type=bind,")]
    assert specs == [f"type=bind,source={tmp_path},target={tmp_path}"]


def test_wrapper_has_no_host_python_or_secret_environment(tmp_path):
    fake = tmp_path / "docker"
    log = tmp_path / "args"
    fake.write_text('#!/bin/sh\nprintf "%s\\n" "$@" >> "$CAPTURE"\n')
    fake.chmod(0o700)
    key = tmp_path / "keys.json"
    key.write_text("{}")
    result = subprocess.run(
        [
            "bash",
            str(ROOT / "docker/credentials.sh"),
            "--image",
            "local:test",
            "check",
            "--bundle",
            str(tmp_path),
            "--key-file",
            str(key),
        ],
        env={**os.environ, "PATH": f"{tmp_path}:/usr/bin:/bin", "CAPTURE": str(log)},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    args = log.read_text()
    assert "--pull=never" in args and "--network\nnone" in args
    assert "--read-only" in args and "readonly" in args
    assert "bisheng.core.config.credential_tool" in args
    assert "--env-file" not in args and "MYSQL_PWD" not in args


def test_online_requires_explicit_network():
    result = subprocess.run(
        ["bash", str(ROOT / "docker/credentials.sh"), "--image", "local:test", "check", "--online"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "network" in result.stderr


def test_installer_preparation_precedes_service_start():
    text = (ROOT / "docker/install.sh").read_text()
    assert "credentials.sh" in text
    assert text.index("credential_setup\n") < text.index("compose up -d")
    helper = (ROOT / "docker/lib/credential-install.sh").read_text()
    assert "check --bundle" in helper and "--enforce" in helper
    assert "MINIO_ROOT_PASSWORD" not in text


def test_deployment_env_template_is_unambiguous():
    from bisheng.core.config.credential_loader import read_env_file

    values = read_env_file(ROOT / "docker/.env.example")
    assert values["BISHENG_CREDENTIALS_DIR"] == ""
    assert values["BISHENG_SECRET_KEYS_FILE"] == ""
    assert "MINIO_ROOT_PASSWORD" not in values
    assert "BISHENG_GATEWAY_HMAC_SECRET" in values
    text = (ROOT / "docker/install.sh").read_text()
    assert "--no-deps --force-recreate backend backend_worker" in text


def test_prepare_only_does_not_pull_login_or_start_services(tmp_path):
    import shutil

    deployment = tmp_path / "docker"
    deployment.mkdir()
    for name in ("install.sh", "credentials.sh", ".env.example"):
        shutil.copyfile(ROOT / "docker" / name, deployment / name)
    shutil.copytree(ROOT / "docker/lib", deployment / "lib")
    binaries = tmp_path / "bin"
    binaries.mkdir()
    log = tmp_path / "docker-commands"
    fake = binaries / "docker"
    fake.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$CAPTURE"\nexit 0\n')
    fake.chmod(0o700)
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "manifest.json").write_text('{"version": 1, "revision": "' + "a" * 32 + '"}')
    key = tmp_path / "keys.json"
    key.write_text("{}")
    key.chmod(0o600)
    result = subprocess.run(
        [
            "bash",
            str(deployment / "install.sh"),
            "--prepare-only",
            "--bundle",
            str(bundle),
            "--key-file",
            str(key),
            "--revision",
            "a" * 32,
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": f"{binaries}:/usr/bin:/bin", "CAPTURE": str(log)},
    )
    assert result.returncode == 0, result.stderr
    calls = log.read_text().splitlines()
    assert any("credential_tool check" in line for line in calls)
    assert not any(line.startswith(("login ", "pull ")) or " up " in line for line in calls)
    assert key.stat().st_mode & 0o777 == 0o600  # installer never relaxes the external key


def test_wrapper_help_with_no_mounts_works_on_system_bash(tmp_path):
    fake = tmp_path / "docker"
    log = tmp_path / "args"
    fake.write_text('#!/bin/sh\nprintf "%s\\n" "$@" >> "$CAPTURE"\n')
    fake.chmod(0o700)
    response = subprocess.run(
        ["bash", str(ROOT / "docker/credentials.sh"), "--image", "local:test", "--help"],
        env={**os.environ, "PATH": f"{tmp_path}:/usr/bin:/bin", "CAPTURE": str(log)},
        capture_output=True,
        text=True,
    )
    assert response.returncode == 0, response.stderr
    assert "--help" in log.read_text()
