"""Rotation seals control state while explicit native mounts remain private plaintext."""

import hashlib
import json
import stat
from pathlib import Path

import pytest

from bisheng.core.config import credential_rotation as state
from bisheng.core.config.credential_artifacts import bundle_native_files
from bisheng.core.config.secret_crypto import CredentialConfigurationError
from test.core.test_credential_rotation import rotation_deployment as _rotation_deployment

# Re-export the fixture without shadowing an imported binding in test parameters.
rotation_deployment = _rotation_deployment


def assert_private_native_bundle(root, key_file):
    """Whitelist only manifest-declared native basenames, never an entire stage."""
    root = Path(root)
    manifest = json.loads((root / "manifest.json").read_bytes())
    assert manifest["native_storage"] == "plaintext"
    permitted = {
        "mysql.password",
        "mysql-client.cnf",
        "openfga.yaml",
        "openfga.env",
        "redis.password",
        "redis-users.acl",
        "redis.conf",
        "minio.user",
        "minio.password",
        "elasticsearch.password",
        "gateway-application.yml",
        "milvus.yaml",
    }
    names = manifest["native_files"]
    assert isinstance(names, list) and len(names) == len(set(names))
    assert set(names) <= permitted
    assert all(Path(name).name == name for name in names)
    native = bundle_native_files(root, key_file)
    # This fixture has no additional nested security configuration: do not silently
    # exempt newly introduced native paths without reviewing their explicit names.
    assert set(native) == set(names)
    allowed = set()
    for name in names:
        path = root / name
        assert not path.is_symlink() and path.is_file()
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert path.read_bytes() == native[name]
        allowed.add(path)
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    return allowed


def test_control_state_encrypted_and_native_mounts_private(rotation_deployment):
    create, base, key, _ = rotation_deployment
    old = bundle_native_files(base, key)
    session = create(("mysql", "redis"))
    plan = state.read_plan(session, key_file=key)
    expected = [old["mysql.password"], old["redis.password"]]
    new = {name: bundle_native_files(plan["stages"][name], key)[name + ".password"] for name in ("mysql", "redis")}
    expected.extend(new.values())
    source_native = bundle_native_files(plan["source"], key)
    captured_native = bundle_native_files(session / "captured-base", key)
    assert source_native == old
    assert captured_native == old
    active_passwords = {name: old[name + ".password"] for name in ("mysql", "redis")}
    for name in ("mysql", "redis"):
        active_passwords[name] = new[name]
        staged = bundle_native_files(plan["stages"][name], key)
        for component, password in active_passwords.items():
            assert staged[component + ".password"] == password
    allowed = set()
    roots = [Path(plan["source"]), session / "captured-base", *(Path(path) for path in plan["stages"].values())]
    assert {path.parent for path in session.rglob("manifest.json")} == set(roots)
    for root in roots:
        allowed.update(assert_private_native_bundle(root, key))
    assert allowed
    for p in session.rglob("*"):
        if p.is_dir():
            assert not p.is_symlink() and stat.S_IMODE(p.stat().st_mode) == 0o700
        elif p.is_file() and p not in allowed:
            assert not any(v in p.read_bytes() for v in expected), str(p.relative_to(session))
    assert json.loads((session / "inventory.json").read_bytes())["format"] == "bisheng.credentials.v2"
    assert json.loads((session / "env.before").read_bytes())["format"] == "bisheng.credentials.v2"
    assert state._read(session / "env.before").startswith(b"BISHENG_")
    for name, digest in plan["artifacts"].items():
        assert hashlib.sha256((session / name).read_bytes()).hexdigest() == digest


def test_ciphertext_tamper_blocks_resume(rotation_deployment):
    create, _, key, _ = rotation_deployment
    session = create(("redis",))
    p = session / "inputs/redis.password"
    p.write_bytes(p.read_bytes()[:-8] + b"XXXXXXXX")
    with pytest.raises(CredentialConfigurationError):
        state.read_plan(session, key_file=key)
