"""AC-37, AC-49, AC-51: root drop preserves secret groups without weakening modes."""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def test_standard_compose_uses_group_preserving_entrypoint():
    import yaml

    redis = yaml.safe_load((ROOT / "docker/docker-compose.yml").read_text())["services"]["redis"]
    assert redis["entrypoint"] == ["sh", "/credential-entrypoint.sh"]
    assert "./redis/credential-entrypoint.sh:/credential-entrypoint.sh:ro" in redis["volumes"]
    assert any("redis-users.acl:/run/secrets/redis-users.acl:ro" in str(v) for v in redis["volumes"])
    assert redis["command"] == ["redis-server", "/etc/redis.conf", "--aclfile", "/run/secrets/redis-users.acl"]


def test_drop_user_keeps_explicit_groups_and_vendor_arguments(tmp_path):
    bin = tmp_path / "bin"
    bin.mkdir()
    programs = {
        "id": 'if [ "$1" = -u ]; then echo 0; else echo "0 1200"; fi',
        "find": "exit 0",
        "setpriv": 'printf "%s\\n" "$@" > "$CAPTURE"',
    }
    for name, body in programs.items():
        p = bin / name
        p.write_text("#!/bin/sh\n" + body + "\n")
        p.chmod(0o700)
    log = tmp_path / "args"
    result = subprocess.run(
        [
            "sh",
            str(ROOT / "docker/redis/credential-entrypoint.sh"),
            "redis-server",
            "/etc/redis.conf",
            "--aclfile",
            "/run/secrets/redis-users.acl",
        ],
        env={**os.environ, "PATH": str(bin) + ":/usr/bin:/bin", "CAPTURE": str(log)},
        cwd=tmp_path,
        capture_output=True,
    )
    assert result.returncode == 0
    assert log.read_text().splitlines() == [
        "--reuid",
        "redis",
        "--regid",
        "redis",
        "--groups",
        "0,1200",
        "/usr/local/bin/docker-entrypoint.sh",
        "redis-server",
        "/etc/redis.conf",
        "--aclfile",
        "/run/secrets/redis-users.acl",
    ]
