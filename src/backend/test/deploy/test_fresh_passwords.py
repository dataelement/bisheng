"""AC-77-79: exercise the installer's terminal and real offline credential tool, without Docker."""
# ruff: noqa: RUF001 -- assert exact localized terminal prompts.

import os
import pty
import re
import select
import subprocess
import sys
from pathlib import Path

from bisheng.core.config.credential_artifacts import read_confidential
from bisheng.core.config.credential_loader import load_config, read_env_file
from bisheng.core.config.credential_tool import _fresh_generatable

ROOT = Path(__file__).resolve().parents[4]
CONFIG = ROOT / "docker/bisheng/config/config.yaml"
NAMES = ["mysql", "redis", "minio", "elasticsearch", "milvus"]
GENERATED_LINE = re.compile(r"(?m)^(?:MySQL|Redis|MinIO|Elasticsearch|Milvus)：([A-Za-z0-9_-]{10})\r?$".encode())
SCRIPT = """set -euo pipefail
umask 077
source "$SCRIPT_DIR/lib/install-env.sh"
source "$SCRIPT_DIR/lib/credential-install.sh"
die() { exit 2; }
credential_generated_labels=(); credential_generated_values=()
credential_tool() { "$PYTHON" -m bisheng.core.config.credential_tool "$@"; }
credential_collect_inputs
credential_show_generated >"$credential_store/log" 2>&1
"""


def environment(folder):
    folder.mkdir(exist_ok=True)
    envfile = folder / "env"
    shipped = (ROOT / "docker/.env.example").read_text()
    values = read_env_file(ROOT / "docker/.env.example")
    names = set(re.findall(r"^\s*[^#\n]+?!env \$\{(\w+)\}", CONFIG.read_text(), re.M))
    envfile.write_text(shipped + "".join(f"\n{name}=\n" for name in names - values.keys()))
    key = str(folder / "key.json")
    env = dict(
        os.environ,
        PYTHONPATH=str(ROOT / "src/backend"),
        PYTHON=sys.executable,
        SCRIPT_DIR=str(ROOT / "docker"),
        credential_config=str(CONFIG),
        credential_store=str(folder),
        KEY_FILE=key,
        ENV_FILE=str(envfile),
        credential_deployment_id="fresh-pty",
        BUNDLE=str(folder / "bundle"),
    )
    subprocess.run(
        [sys.executable, "-m", "bisheng.core.config.credential_tool", "keygen", "--out", key],
        env=env,
        check=True,
        capture_output=True,
    )
    return env


def terminal(env, replies):
    pid, master = pty.fork()
    if pid == 0:
        os.execvpe("bash", ["bash", "-c", SCRIPT], env)
    buf = b""
    consumed = b""
    try:
        for expected, reply in replies:
            while expected.encode() not in buf:
                assert select.select([master], [], [], 15)[0], "installer prompt timeout"
                chunk = os.read(master, 65536)
                assert chunk, "installer exited before prompt"
                buf += chunk
            head, buf = buf.split(expected.encode(), 1)
            consumed += head + expected.encode()
            os.write(master, reply)
        while select.select([master], [], [], 15)[0]:
            try:
                chunk = os.read(master, 65536)
            except OSError:
                break  # Linux PTYs return EIO on slave close.
            if not chunk:
                break
            buf += chunk
        else:
            raise AssertionError("installer did not exit")
    finally:
        os.close(master)
        _, status = os.waitpid(pid, 0)
    return os.waitstatus_to_exitcode(status), consumed + buf


def test_first_run_secrets_and_redirected_output(tmp_path):
    groups = []
    for i in range(2):
        folder = tmp_path / str(i)
        env = environment(folder)
        status, tail = terminal(env, [("[直接回车随机生成] 请输入", b"\n")] * 5)
        assert status == 0
        values = GENERATED_LINE.findall(tail)
        assert len(values) == len(set(values)) == 5
        assert not any(v in (folder / "log").read_bytes() for v in values)
        assert str(folder / "bundle") in (folder / "log").read_text()
        for name, value in zip(NAMES, values, strict=True):
            stored = read_confidential(
                folder / "inputs" / (name + ".password"), key_file=env["KEY_FILE"], deployment="fresh-pty"
            )
            assert stored == value
        groups.extend(values)
        status, tail = terminal(env, [])
        assert status == 0 and not any(v in tail for v in values)
    assert len(set(groups)) == 10


def test_mixed_manual_and_generated(tmp_path):
    env = environment(tmp_path)
    manual = os.urandom(18).hex().encode()
    replies = [("请输入MySQL密码", manual + b"\n"), ("请再次输入确认", manual + b"\n")]
    status, tail = terminal(env, replies + [("[直接回车随机生成] 请输入", b"\n")] * 4)
    assert status == 0 and manual not in tail
    assert len(GENERATED_LINE.findall(tail)) == 4 and "MySQL：".encode() not in tail


def test_interrupt_and_resume(tmp_path):
    env = environment(tmp_path)
    status, tail = terminal(env, [("[直接回车随机生成] 请输入", b"\n"), ("[直接回车随机生成] 请输入", b"\x04")])
    assert status != 0 and not GENERATED_LINE.search(tail)
    saved = (tmp_path / "inputs/mysql.password").read_bytes()
    status, tail = terminal(env, [("请输入Redis密码（至少6位，输入隐藏）：", b"\x04")])
    assert status != 0 and "[直接回车随机生成]".encode() not in tail
    assert (tmp_path / "inputs/mysql.password").read_bytes() == saved


def test_noninteractive_does_not_consume_first_prompt(tmp_path):
    env = environment(tmp_path)
    result = subprocess.run(["bash", "-c", SCRIPT], stdin=subprocess.DEVNULL, env=env, capture_output=True)
    assert result.returncode and not (tmp_path / "fresh-prompt.started").exists()
    assert terminal(env, [("[直接回车随机生成] 请输入", b"\x04")])[0] != 0
    assert terminal(env, [("请输入MySQL密码（至少6位，输入隐藏）：", b"\x04")])[0] != 0


def test_external_or_configured_endpoints_not_eligible(tmp_path):
    env = environment(tmp_path)
    data = load_config(CONFIG, env_file=env["ENV_FILE"]).data
    assert list(_fresh_generatable(data)) == NAMES
    data["database_url"] += "changed"
    data["celery_redis_url"] = "redis://other:6379/2"
    data["object_storage"]["minio"]["secret_key"] = "already-set"
    data["vector_stores"]["elasticsearch"]["ssl_verify"] = {"basic_auth": ["elastic", "already-set"]}
    data["vector_stores"]["milvus"]["connection_args"] = {"host": "other", "port": 19530}
    assert not list(_fresh_generatable(data))
