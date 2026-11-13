"""Offline CLI contracts: AC-02/06/08/09/10/37."""

import json
import subprocess
import sys

MODULE = "bisheng.core.config.credential_tool"


def run(*args):
    return subprocess.run([sys.executable, "-m", MODULE, *map(str, args)], capture_output=True, text=True, timeout=10)


def test_keygen_is_explicit_and_does_not_overwrite(tmp_path):
    target = tmp_path / "keys.json"
    first = run("keygen", "--out", target)
    assert first.returncode == 0, first.stderr
    keyfile = target.read_bytes()
    assert json.loads(keyfile)["version"] == 1
    assert (target.stat().st_mode & 0o777) == 0o600
    assert json.loads(keyfile)["keys"][0] not in first.stdout + first.stderr
    second = run("keygen", "--out", target)
    assert second.returncode == 2
    assert target.read_bytes() == keyfile


def test_missing_command_and_bad_input_are_redacted(tmp_path):
    marker = "must-not-be-echoed-credential"
    response = run("check", "--password", marker)
    assert response.returncode == 2
    assert marker not in response.stdout + response.stderr


def test_help_does_not_require_key_or_services():
    response = run("--help")
    assert response.returncode == 0
    assert "prepare" in response.stdout


def test_existing_wrong_keyfile_not_replaced(tmp_path):
    target = tmp_path / "keys.json"
    target.write_text("invalid-document")
    response = run("keygen", "--out", target)
    assert response.returncode == 2
    assert target.read_text() == "invalid-document"


def test_real_cli_prepares_checked_in_template_and_validates_native_consumers(tmp_path, monkeypatch):
    import secrets
    from pathlib import Path

    import yaml

    root = Path(__file__).resolve().parents[4]
    key = tmp_path / "keys.json"
    assert run("keygen", "--out", key).returncode == 0
    manifest = {"version": 1}
    values = []
    for name in ("mysql", "redis", "minio", "elasticsearch", "milvus"):
        value = secrets.token_urlsafe(18) + '@:#$\\"'
        file = tmp_path / (name + ".password")
        file.write_text(value)
        values.append(value)
        manifest[name] = {"secret_key_file" if name == "minio" else "password_file": str(file)}
    user = tmp_path / "minio.user"
    user.write_text("minioadmin")
    manifest["minio"]["access_key_file"] = str(user)
    inputs = tmp_path / "inputs.yaml"
    inputs.write_text(yaml.safe_dump(manifest))
    env = tmp_path / "deploy.env"
    env.write_text("BISHENG_GATEWAY_HMAC_SECRET=\n")
    monkeypatch.delenv("BISHENG_GATEWAY_HMAC_SECRET", raising=False)
    bundle = tmp_path / "bundle"
    result = run(
        "prepare",
        "--config",
        root / "docker/bisheng/config/config.yaml",
        "--inputs",
        inputs,
        "--key-file",
        key,
        "--out-dir",
        bundle,
        "--env-file",
        env,
        "--deployment-root",
        root / "docker",
    )
    assert result.returncode == 0, result.stderr
    assert all(value not in result.stdout + result.stderr for value in values)
    assert run("check", "--bundle", bundle, "--key-file", key, "--env-file", env, "--enforce").returncode == 0
    before = (bundle / "mysql-client.cnf").read_bytes()
    (bundle / "mysql-client.cnf").write_text("[client]\npassword=mismatched\n")
    failure = run("check", "--bundle", bundle, "--key-file", key, "--env-file", env)
    assert failure.returncode == 2
    assert "mismatched" not in failure.stderr
    (bundle / "mysql-client.cnf").write_bytes(before)


def test_installer_internal_commands_join_keys_privately_without_overwrite(tmp_path):
    primary, retiring, output = (tmp_path / name for name in ("primary.json", "retiring.json", "transition.json"))
    for file in (primary, retiring):
        assert run("keygen", "--out", file).returncode == 0
        assert run("validate-keyring", "--key-file", file).returncode == 0
    result = run("join-keyrings", "--primary-file", primary, "--retiring-file", retiring, "--out", output)
    assert result.returncode == 0, result.stderr
    keys = [json.loads(file.read_text())["keys"][0] for file in (primary, retiring)]
    assert json.loads(output.read_text())["keys"] == keys
    assert output.stat().st_mode & 0o777 == 0o600
    assert all(key not in result.stdout + result.stderr for key in keys)
    before = output.read_bytes()
    assert run("join-keyrings", "--primary-file", primary, "--retiring-file", retiring, "--out", output).returncode == 2
    assert output.read_bytes() == before
    retiring.write_text("invalid-key-document")
    assert run("validate-keyring", "--key-file", retiring).returncode == 2
    assert (
        run(
            "join-keyrings", "--primary-file", primary, "--retiring-file", retiring, "--out", tmp_path / "failed.json"
        ).returncode
        == 2
    )
    assert not (tmp_path / "failed.json").exists()


def test_installer_requirements_and_inputs_do_not_need_keyring(tmp_path):
    import secrets

    import yaml

    config = tmp_path / "source.yaml"
    config.write_text(yaml.safe_dump({"telemetry_elasticsearch": {"url": "https://stats.example.invalid"}}))
    response = run("requirements", "--config", config)
    assert response.returncode == 0, response.stderr
    assert response.stdout.splitlines() == [
        "mysql",
        "redis",
        "minio",
        "elasticsearch",
        "milvus",
        "telemetry_elasticsearch",
    ]
    password = tmp_path / "password"
    password.write_text(secrets.token_urlsafe(24))
    manifest = tmp_path / "inputs.yaml"
    manifest.write_text(yaml.safe_dump({"version": 1, "mysql": {"password_file": str(password)}}))
    response = run("validate-inputs", "--inputs", manifest)
    assert response.returncode == 0 and password.read_text() not in response.stdout + response.stderr
    password.write_text("1234")
    assert run("validate-inputs", "--inputs", manifest).returncode == 2
    config.write_text("telemetry_elasticsearch: invalid\n")
    assert run("requirements", "--config", config).returncode == 2
