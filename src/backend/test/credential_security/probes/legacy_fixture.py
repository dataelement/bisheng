"""Create an explicitly disposable v1 baseline to test plaintext migration.

This is acceptance setup, never an installer entry point. The existing fixture
credentials are intentionally materialized once as private v1 files; the actual
installer must back them up as ciphertext and remove them after verified switch.
"""

import argparse
import json
import os
from pathlib import Path

import yaml
from sealed_fixture import checked_root


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    root = checked_root(args.root)
    if os.geteuid() != 1000:
        raise SystemExit("dedicated ordinary deployment UID required")
    from bisheng.core.config.credential_artifacts import bundle_native_files, write_confidential, write_private_atomic
    from bisheng.core.config.credential_loader import read_env_file

    env_file = root / "docker/.env"
    env = read_env_file(env_file)
    source = Path(env["BISHENG_CREDENTIALS_DIR"])
    key = Path(env["BISHENG_SECRET_KEYS_FILE"])
    store = root / "docker/.generated/credential-security"
    target = store / "revisions/legacy-fixture-v1"
    marker = root / "control/legacy-fixture.json"
    if marker.exists() or target.exists() or (store / "rotation.active").exists():
        raise SystemExit("existing fixture or unfinished rotation must not be overwritten")
    manifest = json.loads((source / "manifest.json").read_bytes())
    native = bundle_native_files(source, key)
    backup = root / "control/environment-before-legacy-fixture.sealed"
    write_confidential(backup, env_file.read_bytes(), key_file=key, deployment=manifest["deployment_id"])
    target.mkdir(mode=0o700)
    names = []
    for name, value in native.items():
        if "/" in name:
            continue
        if name == "redis.conf":
            value += b"\nmaxclients 23456\n"
        write_private_atomic(target / name, value, mode=0o640)
        names.append(name)
    write_private_atomic(target / "config.yaml", (source / "config.yaml").read_bytes(), mode=0o640)
    for name in ["roles", "native_sha256", "deployment_id", "runtime_seeded"]:
        manifest.pop(name, None)
    manifest.update(version=1, native_files=sorted(names))
    write_private_atomic(target / "manifest.json", json.dumps(manifest).encode(), mode=0o640)
    health = root / "control/legacy-redis-health.sh"
    write_private_atomic(health, (root / "docker/redis/credential-health.sh").read_bytes().replace(b"/run/bisheng-secrets/files/", b"/run/secrets/"), mode=0o640)
    compose = {
        "services": {"redis": {
            "container_name": "rotation-acceptance-166-sealed-v2-redis", "image": env["REDIS_IMAGE"],
            "group_add": [str(os.getgid())], "environment": {"TZ": "Asia/Shanghai"},
            "entrypoint": ["sh", "/credential-entrypoint.sh"],
            "command": ["redis-server", "/etc/redis.conf", "--aclfile", "/run/secrets/redis-users.acl"],
            "volumes": [str(root / "docker/data/redis") + ":/data",
                        str(target / "redis.conf") + ":/etc/redis.conf:ro",
                        str(target / "redis.password") + ":/run/secrets/redis.password:ro",
                        str(target / "redis-users.acl") + ":/run/secrets/redis-users.acl:ro",
                        str(health) + ":/credential-health.sh:ro",
                        str(root / "docker/redis/credential-entrypoint.sh") + ":/credential-entrypoint.sh:ro"],
            "healthcheck": {"test": ["CMD", "sh", "/credential-health.sh"], "interval": "3s", "timeout": "3s", "retries": 10},
        }}, "networks": {"default": {"external": True, "name": "rotation-acceptance-166-sealed-v2"}},
    }
    write_private_atomic(root / "control/legacy-redis.yml", yaml.safe_dump(compose).encode())
    lines = env_file.read_text().splitlines()
    lines = ["BISHENG_CREDENTIALS_DIR=" + str(target) if line.startswith("BISHENG_CREDENTIALS_DIR=") else line for line in lines]
    write_private_atomic(env_file, ("\n".join(lines) + "\n").encode())
    write_private_atomic(marker, json.dumps({"legacy": str(target), "previous_bundle": str(source), "intentional_plaintext_baseline": True}).encode())
    print(json.dumps({"status": "legacy_fixture_prepared", "passwords_changed": False}))


if __name__ == "__main__":
    main()
