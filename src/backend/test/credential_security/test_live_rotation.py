"""覆盖 AC: AC-48, AC-49, AC-50, AC-51, AC-52, AC-54, AC-56.

Opt-in host-level original-command acceptance. Native account assertions run
inside the matching release image; the host never imports live app settings.
The fixture must be independently created and must not contain customer data.
"""

import json
import os
import secrets
import subprocess
from pathlib import Path

import pytest
import yaml


def _env(path):
    from bisheng.core.config.credential_loader import read_env_file

    return read_env_file(path)


def _set_env(path, name, value):
    script = path.parent / "lib/install-env.sh"
    result = subprocess.run(
        [
            "bash",
            "-c",
            'SCRIPT_DIR=$(dirname "$(dirname "$1")"); die() { exit 2; }; source "$1"; env_set "$2" "$3" "$4"',
            "fixture",
            str(script),
            str(path),
            name,
            value,
        ],
        capture_output=True,
    )
    assert result.returncode == 0, "disposable fixture environment update failed"


def _run(root, *, overrides=None, success=True):
    result = subprocess.run(
        ["bash", str(root / "install.sh"), "--no-gateway"],
        env={**os.environ, "BISHENG_ALLOW_CREDENTIAL_ROTATION": "yes", **(overrides or {})},
        capture_output=True,
        timeout=600,
    )
    # Do not include captured logs in assertion messages; failures may originate
    # from a vendor tool. Only the private fixture directory holds evidence.
    evidence = root / ".generated/last-rotation-test.log"
    evidence.write_bytes(result.stdout + result.stderr)
    evidence.chmod(0o600)
    if success:
        assert result.returncode == 0, "original-command rotation failed; inspect private fixture evidence"
    else:
        assert result.returncode != 0, "fault boundary was not reached"
    return result


def _request(root, selected):
    folder = root / ".generated" / ("live-inputs-" + secrets.token_hex(8))
    folder.mkdir(mode=0o700, parents=True)
    data = {"version": 1}
    for name in selected:
        file = folder / name
        file.write_text(secrets.token_urlsafe(25) + "@$#%")
        file.chmod(0o600)
        data[name] = {"secret_key_file" if name == "minio" else "password_file": name}
    manifest = folder / "request.yaml"
    manifest.write_text(yaml.safe_dump(data))
    manifest.chmod(0o600)
    _set_env(root / ".env", "BISHENG_CREDENTIAL_ROTATION_INPUTS_FILE", str(manifest))


def _completed(root, selected):
    store = root / ".generated/credential-security"
    assert not (store / "rotation.active").exists(), "unfinished maintenance remains"
    sessions = []
    for path in (store / "rotations").iterdir():
        if (path / "plan.json").exists():
            plan = json.loads((path / "plan.json").read_text())
            journal = json.loads((path / "journal.json").read_text())
            if journal["phase"] == "COMPLETE":
                sessions.append((path.stat().st_mtime_ns, plan, journal))
    assert sessions, "no completed native rotation evidence"
    _, plan, journal = max(sessions, key=lambda x: x[0])
    assert set(plan["selected"]) == set(selected)
    assert all(c["phase"] == "FILES_PERSISTED" for c in journal["components"].values())
    return len(sessions)


@pytest.mark.parametrize(
    "selected",
    [
        ("mysql",),
        ("redis",),
        ("elasticsearch",),
        ("minio",),
        ("milvus",),
        ("mysql", "redis"),
        ("mysql", "redis", "elasticsearch", "minio", "milvus"),
    ],
)
def test_original_command_rotates_exact_selected_native_accounts(live_rotation_deployment, selected):
    root, _ = live_rotation_deployment
    before = _env(root / ".env")
    key = Path(before["BISHENG_SECRET_KEYS_FILE"]).read_bytes()
    _request(root, selected)
    _run(root)
    _completed(root, selected)
    after = _env(root / ".env")
    assert key == Path(after["BISHENG_SECRET_KEYS_FILE"]).read_bytes(), "password rotation changed deployment key"
    assert before["BISHENG_CREDENTIALS_DIR"] != after["BISHENG_CREDENTIALS_DIR"]


def test_completed_automation_request_is_not_applied_twice(live_rotation_deployment):
    root, _ = live_rotation_deployment
    _request(root, ("redis",))
    _run(root)
    before = _env(root / ".env")["BISHENG_CREDENTIALS_DIR"]
    count = _completed(root, ("redis",))
    _run(root)
    assert _env(root / ".env")["BISHENG_CREDENTIALS_DIR"] == before
    assert _completed(root, ("redis",)) == count


def _fail_persist_once(root, tmp_path):
    import shutil

    delegate = shutil.which("docker")
    assert delegate, "Docker required"
    flag = tmp_path / "fail-once"
    flag.write_text("armed")
    binary = tmp_path / "bin"
    binary.mkdir()
    docker = binary / "docker"
    docker.write_text(
        "#!/usr/bin/env python3\nimport os,sys\nfrom pathlib import Path\na=sys.argv[1:]\nf=Path("
        + repr(str(flag))
        + ")\nif 'bisheng.core.config.credential_tool' in a:\n t=a[a.index('bisheng.core.config.credential_tool')+1:]\n if t[:2]==['rotation','persist'] and f.exists():\n  f.unlink();sys.exit(77)\nos.execv("
        + repr(delegate)
        + ",['docker',*a])\n"
    )
    docker.chmod(0o700)
    _request(root, ("mysql",))
    _run(root, overrides={"PATH": str(binary) + ":" + os.environ["PATH"]}, success=False)
    assert not flag.exists(), "fault was not injected after native verification"
    store = root / ".generated/credential-security"
    session = Path((store / "rotation.active").read_text().strip())
    journal = json.loads((session / "journal.json").read_text())
    assert journal["phase"] == "NEEDS_ATTENTION"
    assert journal["components"]["mysql"]["phase"] == "NATIVE_VERIFIED"
    return session


def _mysql_changed_at(root, cnf):
    command = ["docker", "compose", "--env-file", str(root / ".env"), "-f", str(root / "docker-compose.yml")]
    container = subprocess.run(
        [*command, "ps", "-q", "mysql"], capture_output=True, text=True, check=True
    ).stdout.strip()
    with cnf.open("rb") as stream:
        response = subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                container,
                "mysql",
                "--defaults-extra-file=/dev/stdin",
                "--protocol=socket",
                "--batch",
                "--skip-column-names",
                "--execute=SELECT Host,password_last_changed FROM mysql.user WHERE User='root' ORDER BY Host",
            ],
            stdin=stream,
            capture_output=True,
        )
    assert response.returncode == 0, "fresh native MySQL authentication failed"
    return response.stdout


def test_partial_native_success_resumes_without_repeating_account_write(live_rotation_deployment, tmp_path):
    root, _ = live_rotation_deployment
    session = _fail_persist_once(root, tmp_path)
    plan = json.loads((session / "plan.json").read_text())
    target = session / plan["stages"]["mysql"] / "mysql-client.cnf"
    before = _mysql_changed_at(root, target)
    _run(root)
    assert _mysql_changed_at(root, target) == before, "resume repeated ALTER USER"
    _completed(root, ("mysql",))


def test_interactive_paired_rollback_restores_server_and_configuration(live_rotation_deployment, tmp_path):
    import pty
    import select
    import time

    root, _ = live_rotation_deployment
    session = _fail_persist_once(root, tmp_path)
    plan = json.loads((session / "plan.json").read_text())
    original = session / plan["source"] / "mysql-client.cnf"
    master, slave = pty.openpty()
    environment = {**os.environ, "BISHENG_ALLOW_CREDENTIAL_ROTATION": ""}
    process = subprocess.Popen(
        ["bash", str(root / "install.sh"), "--no-gateway"], stdin=slave, stdout=slave, stderr=slave, env=environment
    )
    os.close(slave)
    received = bytearray()
    pending = bytearray()

    def expect(text):
        marker = text.encode()
        deadline = time.monotonic() + 120
        while marker not in pending:
            assert time.monotonic() < deadline, "rollback terminal prompt timeout"
            if select.select([master], [], [], 0.2)[0]:
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    chunk = b""
                assert chunk, "rollback exited before expected prompt"
                pending.extend(chunk)
                received.extend(chunk)
        del pending[: pending.index(marker) + len(marker)]

    try:
        expect("恢复方式：")  # noqa: RUF001
        os.write(master, b"2\n")
        expect("确认继续请输入yes：")  # noqa: RUF001
        os.write(master, b"yes\n")
        expect("输入yes继续：")  # noqa: RUF001
        os.write(master, b"yes\n")
        deadline = time.monotonic() + 300
        while process.poll() is None and time.monotonic() < deadline:
            if select.select([master], [], [], 0.2)[0]:
                try:
                    received.extend(os.read(master, 65536))
                except OSError:
                    break
        assert process.wait(timeout=5) == 0, "paired rollback failed; inspect private evidence"
    finally:
        (root / ".generated/rollback-terminal.log").write_bytes(received)
        (root / ".generated/rollback-terminal.log").chmod(0o600)
        if process.poll() is None:
            process.kill()
            process.wait()
        os.close(master)
    assert _mysql_changed_at(root, original)
    _completed(root, ("mysql",))
