"""Opt-in disposable non-root CLI fixture; never persists plaintext answers.

An administrator provisions the locked test account and Docker group once.
configure executes as the ordinary account. drive uses runuser solely as an
administrator-owned test harness, then exercises the original installer via PTY.
"""

import argparse
import json
import os
import pty
import pwd
import secrets
import select
import shlex
import signal
import subprocess
import time
from pathlib import Path
from urllib.parse import quote, quote_plus

OWNER = "bisheng-sealed-acceptance-20261114"
PROJECT = "rotation-acceptance-166-sealed-v2"


def checked_root(value):
    root = Path(value).resolve()
    if (
        os.environ.get("BISHENG_SEALED_DISPOSABLE") != "true"
        or not (root / ".owner").is_file()
        or (root / ".owner").read_text().strip() != OWNER
    ):
        raise SystemExit("explicit sealed disposable fixture ownership required")
    return root


def configure(root):
    import yaml

    if os.geteuid() == 0:
        raise SystemExit("configure must run as the ordinary deployment account")
    marker = root / "control/configured"
    if marker.exists():
        return
    path = root / "docker/docker-compose.yml"
    value = yaml.safe_load(path.read_text())
    keep = {
        "mysql", "mysql-init", "openfga-migrate", "openfga", "redis", "elasticsearch",
        "etcd", "minio", "milvus", "backend", "backend_worker", "frontend",
    }
    value["services"] = {k: v for k, v in value["services"].items() if k in keep}
    for name, service in value["services"].items():
        service["container_name"] = PROJECT + "-" + name
        service.pop("profiles", None)
        service.pop("ports", None)
        dependencies = service.get("depends_on", {})
        if isinstance(dependencies, list):
            service["depends_on"] = [n for n in dependencies if n in keep]
        else:
            service["depends_on"] = {n: v for n, v in dependencies.items() if n in keep}
    value["services"]["frontend"]["ports"] = ["127.0.0.1:13002:3001"]
    value["services"]["backend"]["ports"] = ["127.0.0.1:17861:7860"]
    value["services"]["minio"]["ports"] = ["127.0.0.1:19101:9000"]
    value["networks"]["default"]["name"] = PROJECT
    value["networks"]["sandbox_net"]["name"] = PROJECT + "-sandbox"
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
    environment = root / "docker/.env"
    if environment.exists():
        raise SystemExit("unmarked existing environment must not be overwritten")
    images = json.loads((root / "control/images.json").read_text())
    values = {
        **images,
        "BISHENG_BACKEND_IMAGE": "bisheng-sealed-acceptance:20261114",
        "COMPOSE_PROJECT_NAME": PROJECT,
        "BISHENG_NETWORK_NAME": PROJECT,
        "COMPOSE_PROFILES": "",
        "BISHENG_PRO": "false",
        "BISHENG_SECRET_FILE_GID": "",
        "BISHENG_CREDENTIAL_INPUTS_FILE": "",
        "BISHENG_CREDENTIAL_ROTATION_INPUTS_FILE": "",
        "DOCKER_VOLUME_DIRECTORY": ".",
    }
    text = (root / "docker/.env.example").read_text()
    lines = text.splitlines()
    for key, val in values.items():
        if any(c in str(val) for c in "\r\n"):
            raise SystemExit("unsafe nonsecret fixture setting")
        replacement = key + "=" + str(val)
        found = False
        for i, line in enumerate(lines):
            if line.startswith(key + "="):
                lines[i] = replacement
                found = True
        if not found:
            lines.append(replacement)
    environment.write_text("\n".join(lines) + "\n")
    environment.chmod(0o600)
    script = root / "control/install.sh"
    script.write_text(
        "#!/bin/bash\nset -euo pipefail\n"
        "cd " + shlex.quote(str(root)) + "\n"
        'export PATH="$PWD/bin:$PATH" DOCKER_CONFIG="$PWD/control/docker"\n'
        'id -u > "$PWD/control/deployment.uid"\n'
        'bash docker/install.sh --no-gateway\n'
    )
    script.chmod(0o700)
    marker.write_text(OWNER)


def drive(root, account, mode, components):
    account_uid = pwd.getpwnam(account).pw_uid
    if account_uid == 0 or account != "bisheng-cred-v2":
        raise SystemExit("dedicated ordinary fixture account required")
    script = root / "control/install.sh"
    if script.stat().st_uid != account_uid:
        raise SystemExit("installer harness not owned by deployment account")
    labels = [("mysql", "MySQL"), ("redis", "Redis"), ("minio", "MinIO"), ("elasticsearch", "Elasticsearch"), ("milvus", "Milvus")]
    events = []
    values = []
    if mode == "migrate":
        events.append(("\u8f93\u5165yes\u7ee7\u7eed", b"yes"))
    if mode == "resume":
        events.append(("恢复方式", b"1"))
        events.append(("\u8f93\u5165yes\u7ee7\u7eed", b"yes"))
    else:
        for name, label in labels:
            selected = mode == "initial" or (mode == "rotate" and name in components)
            if mode != "initial":
                events.append(("\u662f\u5426\u4fee\u6539" + label + "\u5bc6\u7801", b"y" if selected else b""))
            if selected:
                value = (secrets.token_urlsafe(28) + "@$#%'\\\"").encode()
                values.append(value)
                events.extend([("\u8bf7\u8f93\u5165" + label + "\u5bc6\u7801", value), ("\u8bf7\u518d\u6b21\u8f93\u5165\u786e\u8ba4", value)])
        if mode == "rotate" and components:
            events.append(("\u8f93\u5165yes\u7ee7\u7eed", b"yes"))
    master, slave = pty.openpty()
    proc = subprocess.Popen(["runuser", "-u", account, "--", "bash", str(script)], stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
    os.close(slave)
    transcript = bytearray()
    pending = bytearray()
    index = 0
    deadline = time.monotonic() + 1200
    result = {"mode": mode, "expected_uid": account_uid, "status": "running", "prompts_answered": 0}
    status = root / ("control/drive-" + mode + ".json")
    status.write_text(json.dumps(result))
    try:
        while True:
            if time.monotonic() > deadline:
                os.killpg(proc.pid, signal.SIGTERM)
                result["status"] = "timeout"
                break
            if select.select([master], [], [], 0.3)[0]:
                try:
                    data = os.read(master, 65536)
                except OSError:
                    data = b""
                transcript.extend(data)
                pending.extend(data)
                if len(transcript) > 16 * 1024 * 1024:
                    os.killpg(proc.pid, signal.SIGTERM)
                    result["status"] = "output-limit"
                    break
                if index < len(events):
                    marker, answer = events[index]
                    encoded = marker.encode("utf-8")
                    if encoded in pending:
                        del pending[:pending.index(encoded) + len(encoded)]
                        os.write(master, answer + b"\n")
                        index += 1
                        result["prompts_answered"] = index
                        status.write_text(json.dumps(result))
                if not data and proc.poll() is not None:
                    break
            elif proc.poll() is not None:
                break
        code = proc.wait(timeout=10)
        forms = []
        for value in values:
            text = value.decode()
            forms.extend([value, quote(text, safe="").encode(), quote_plus(text).encode(), json.dumps(text)[1:-1].encode(), repr(text)[1:-1].encode()])
        echoed = any(v in transcript for v in forms)
        if echoed:
            result["status"] = "plaintext-echo-rejected"
        elif result["status"] == "running":
            result["status"] = "passed" if code == 0 and (index == len(events) or mode == "retry") else "failed"
        result["exit_code"] = code
        result["plaintext_echo"] = echoed
        # Never persist an unsanitized transcript, even if the product regresses.
        if not echoed:
            (root / ("control/drive-" + mode + ".safe.log")).write_bytes(transcript)
        status.write_text(json.dumps(result))
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait()
        os.close(master)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["configure", "drive"])
    p.add_argument("--root", required=True)
    p.add_argument("--account", default="bisheng-cred-v2")
    p.add_argument("--mode", choices=["initial", "retry", "retain", "rotate", "resume", "migrate"], default="initial")
    p.add_argument("--components", default="mysql,redis,minio,elasticsearch,milvus")
    args = p.parse_args()
    root = checked_root(args.root)
    if args.action == "configure":
        configure(root)
    else:
        drive(root, args.account, args.mode, set(filter(None, args.components.split(","))))


if __name__ == "__main__":
    main()
