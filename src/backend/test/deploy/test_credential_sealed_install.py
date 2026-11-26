"""The original hidden-input helper streams directly into encrypted artifacts."""

import json
import os
import pty
import select
import shlex
import subprocess
import sys
import time
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parents[4]


@pytest.mark.parametrize("secret", [b"654321", b"abcdef", b"!!!!!!", b"Prompt-only-secret-123@$'\\"])
def test_prompt_writes_only_ciphertext_and_never_echoes_password(tmp_path, monkeypatch, secret):
    key = tmp_path / "key.json"
    key.write_text(json.dumps({"version": 1, "keys": [Fernet.generate_key().decode()]}))
    key.chmod(0o600)
    secret_file = tmp_path / "mysql.password"
    script = tmp_path / "input.sh"
    script.write_text("\n".join([
        "set -euo pipefail", "umask 077",
        "source " + shlex.quote(str(ROOT / "docker/lib/credential-install.sh")),
        "KEY_FILE=" + shlex.quote(str(key)),
        "credential_inputs=" + shlex.quote(str(tmp_path)),
        "credential_deployment_id=prompt-test",
        'die() { printf "%s\\n" "$*" >&2; exit 2; }',
        "credential_tool() { " + shlex.quote(sys.executable) + ' -m bisheng.core.config.credential_tool "$@"; }',
        "credential_prompt_secret mysql MySQL " + shlex.quote(str(secret_file)) + " password_file",
    ]))
    master, slave = pty.openpty()
    proc = subprocess.Popen(["bash", str(script)], stdin=slave, stdout=slave, stderr=slave,
                            env={**os.environ, "PYTHONPATH": str(ROOT / "src/backend")})
    os.close(slave)
    transcript = bytearray()
    pending = bytearray()
    try:
        for marker in ["请输入MySQL密码", "请再次输入确认"]:
            deadline = time.monotonic() + 20
            encoded = marker.encode()
            while encoded not in pending:
                assert time.monotonic() < deadline, "hidden input prompt timeout"
                if select.select([master], [], [], 0.2)[0]:
                    data = os.read(master, 65536)
                    assert data, "input helper exited before prompt"
                    pending.extend(data)
                    transcript.extend(data)
            del pending[:pending.index(encoded) + len(encoded)]
            os.write(master, secret + b"\n")
        proc.wait(timeout=20)
        assert proc.returncode == 0
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        os.close(master)
    assert secret not in transcript
    assert secret not in secret_file.read_bytes()
    from bisheng.core.config.credential_inputs import read_secret

    monkeypatch.setenv("BS_SECRET_KEYS_FILE", str(key))
    monkeypatch.setenv("BS_CREDENTIAL_DEPLOYMENT_ID", "prompt-test")
    assert read_secret(secret_file, allow_plaintext=False).encode() == secret
