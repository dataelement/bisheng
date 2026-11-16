"""Durable native rotation preserves only encrypted sensitive state."""

import hashlib
import json

import pytest

from bisheng.core.config import credential_rotation as state
from bisheng.core.config.credential_artifacts import bundle_native_files
from bisheng.core.config.secret_crypto import CredentialConfigurationError
from test.core.test_credential_rotation import rotation_deployment as rotation_deployment


def test_all_sensitive_plan_copies_are_encrypted(rotation_deployment):
    create, base, key, _ = rotation_deployment
    old = bundle_native_files(base, key)
    session = create(("mysql", "redis"))
    plan = state.read_plan(session, key_file=key)
    expected = [old["mysql.password"], old["redis.password"]]
    for name in ["mysql", "redis"]:
        expected.append(bundle_native_files(plan["stages"][name], key)[name + ".password"])
    for p in session.rglob("*"):
        if p.is_file():
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
