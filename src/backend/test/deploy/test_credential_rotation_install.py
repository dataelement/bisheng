"""覆盖 AC: AC-48, AC-49, AC-50, AC-54, AC-56 — real terminal selection."""

import os
import pty
import select
import shlex
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

from test.core.test_credential_rotation import rotation_deployment as rotation_deployment

ROOT = Path(__file__).resolve().parents[4]


def test_repeated_socket_observations_keep_distinct_encrypted_logs(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "manifest.json").write_text("{}")
    script = r'''
set -euo pipefail
source "$1/docker/lib/credential-rotate.sh"
KEY_FILE=unused
credential_tool() {
  local action=$2 output
  case "$action" in
    native-stream) printf 'fake-cnf-in-memory' ;;
    seal-stream)
      while [[ $# -gt 0 ]]; do
        if [[ $1 = --out ]]; then output=$2; break; fi
        shift
      done
      (set -o noclobber; cat > "$output") ;;
    open-stream) return 1 ;;
  esac
}
docker() { cat >/dev/null; printf 'authenticated\n'; }
first=$(credential_rotation_socket "$2/bundle/mysql-client.cnf" "$2/observation" container)
second=$(credential_rotation_socket "$2/bundle/mysql-client.cnf" "$2/observation" container)
[[ $first = OK && $second = OK ]]
'''
    result = subprocess.run(["bash", "-c", script, "socket-test", str(ROOT), str(tmp_path)], capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr.decode()
    assert len(list(tmp_path.glob("observation.*.sealed"))) == 2


def helper(tmp_path, base, key, env):
    store = tmp_path / "store"
    store.mkdir()
    script = tmp_path / "select.sh"
    lines = ["set -euo pipefail", "umask 077"]
    for file in ("install-env.sh", "credential-install.sh", "credential-rotate.sh"):
        lines.append("source " + shlex.quote(str(ROOT / "docker/lib" / file)))
    for name, value in {
        "credential_store": store,
        "BUNDLE": base,
        "KEY_FILE": key,
        "ENV_FILE": env,
        "SCRIPT_DIR": ROOT / "docker",
    }.items():
        lines.append(name + "=" + shlex.quote(str(value)))
    lines += [
        'die() { printf "%s\\n" "$*" >&2; exit 1; }',
        "credential_has_old_data() { return 0; }",
        "credential_tool() { " + shlex.quote(sys.executable) + ' -m bisheng.core.config.credential_tool "$@"; }',
        'credential_rotation_tool() { credential_tool rotation "$@"; }',
        "credential_rotation_select",
        'printf "%s\\n" "$credential_rotation_manifest" > ' + shlex.quote(str(tmp_path / "selected-path")),
    ]
    script.write_text("\n".join(lines))
    return script


@pytest.mark.parametrize("selected", [(), ("redis",), ("mysql", "minio", "milvus")])
def test_default_retain_and_exact_selected_passwords(rotation_deployment, tmp_path, selected):
    _, base, key, env = rotation_deployment
    script = helper(tmp_path, base, key, env)
    master, slave = pty.openpty()
    proc = subprocess.Popen(
        ["bash", str(script)],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src/backend")},
    )
    os.close(slave)
    received = bytearray()
    pending = bytearray()

    def expect(marker):
        marker = marker.encode()
        deadline = time.monotonic() + 15
        while marker not in pending:
            assert time.monotonic() < deadline, "selection prompt timeout"
            if select.select([master], [], [], 0.2)[0]:
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    chunk = b""
                assert chunk, received.decode(errors="replace")
                pending.extend(chunk)
                received.extend(chunk)
        del pending[: pending.index(marker) + len(marker)]

    secret = "New-rotation-password-123@:$#"
    try:
        for name, label in (
            ("mysql", "MySQL"),
            ("redis", "Redis"),
            ("minio", "MinIO"),
            ("elasticsearch", "Elasticsearch"),
            ("milvus", "Milvus"),
        ):
            expect("是否修改" + label + "密码？[y/N]：")  # noqa: RUF001
            os.write(master, b"y\n" if name in selected else b"\n")
            if name in selected:
                expect("输入隐藏）：")  # noqa: RUF001
                os.write(master, (secret + "\n").encode())
                expect("请再次输入确认：")  # noqa: RUF001
                os.write(master, (secret + "\n").encode())
        assert proc.wait(timeout=15) == 0
        path = (tmp_path / "selected-path").read_text().strip()
        if selected:
            request = yaml.safe_load(Path(path).read_text())
            assert set(request) - {"version"} == set(selected)
        else:
            assert path == ""
        assert secret not in received.decode(errors="replace")
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        os.close(master)


def test_noninteractive_without_request_reuses(rotation_deployment, tmp_path):
    _, base, key, env = rotation_deployment
    script = helper(tmp_path, base, key, env)
    result = subprocess.run(
        ["bash", str(script)],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src/backend")},
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "selected-path").read_text().strip() == ""


def test_resume_marker_uses_saved_plan_before_any_new_password(rotation_deployment, tmp_path):
    _, base, key, env = rotation_deployment
    script = helper(tmp_path, base, key, env)
    saved = tmp_path / "store/rotations/saved"
    saved.mkdir(parents=True)
    (saved / "plan.json").write_text("{}")
    (tmp_path / "store/rotation.active").write_text(str(saved) + "\n")
    result = subprocess.run(["bash", str(script)], capture_output=True, text=True)
    assert result.returncode == 0
    assert "不重复输入" in result.stdout
    assert "是否修改" not in result.stdout
