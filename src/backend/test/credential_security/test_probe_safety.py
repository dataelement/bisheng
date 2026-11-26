"""AC-51: business acceptance helpers refuse unmarked/non-opted-in environments."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("name", ["business_probe.py", "data_probe.py", "worker_probe.py", "safe_probe.py"])
def test_business_probe_requires_explicit_disposable_ownership(name):
    path = Path(__file__).parent / "probes" / name
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2])}
    env.pop("BISHENG_ROTATION_BUSINESS_DISPOSABLE", None)
    result = subprocess.run([sys.executable, str(path), "verify"], env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode != 0
    assert "explicit disposable fixture ownership required" in result.stderr


def test_probe_error_is_encrypted_without_sdk_message_in_stdout(tmp_path, monkeypatch, capsys):
    import importlib.util
    import json

    from cryptography.fernet import Fernet

    from bisheng.core.config.credential_artifacts import read_confidential

    location = Path(__file__).parent / "probes/safe_probe.py"
    spec = importlib.util.spec_from_file_location("safe_acceptance_probe", location)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    owner = "rotation-acceptance-166-sealed-v2"
    data = tmp_path / "data"
    data.mkdir()
    (data / ".credential-acceptance-owner").write_text(owner)
    key = tmp_path / "keys.json"
    key.write_text(json.dumps({"version": 1, "keys": [Fernet.generate_key().decode()]}))
    key.chmod(0o600)
    monkeypatch.setenv("BS_SECRET_KEYS_FILE", str(key))
    monkeypatch.setenv("BISHENG_ROTATION_BUSINESS_DISPOSABLE", "true")
    monkeypatch.setenv("BISHENG_ROTATION_EXPECTED_OWNER", owner)
    monkeypatch.setattr(sys, "argv", ["safe_probe.py", "data", "verify"])

    def path(value):
        value = str(value)
        return data / value.removeprefix("/app/data/") if value.startswith("/app/data/") else Path(value)

    monkeypatch.setattr(module, "Path", path)
    secret = "test-only-SDK-error-secret-123456"

    def unsafe(*args, **kwargs):
        print("SDK output " + secret)
        raise RuntimeError(secret)

    monkeypatch.setattr(module.runpy, "run_path", unsafe)
    assert module.main() == 1
    captured = capsys.readouterr()
    assert secret not in captured.out + captured.err
    result = json.loads(captured.out)
    assert result["error_type"] == "RuntimeError"
    encrypted = data / "credential-acceptance" / result["encrypted_diagnostic"]
    assert secret.encode() not in encrypted.read_bytes()
    assert secret.encode() in read_confidential(encrypted, key_file=key, deployment=owner)
