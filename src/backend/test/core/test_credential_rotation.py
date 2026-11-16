"""AC-48, AC-50, AC-52, AC-54, AC-56: durable plans, exact selection and safe resume decisions."""

import json
import secrets
from pathlib import Path

import pytest
import yaml
from cryptography.fernet import Fernet

from bisheng.core.config.credential_artifacts import bundle_native_files, write_confidential
from bisheng.core.config.credential_bundle import prepare_bundle
from bisheng.core.config.secret_crypto import CredentialConfigurationError, get_keyring


@pytest.fixture
def rotation_deployment(tmp_path, monkeypatch):
    from bisheng.core.config.credential_rotation import prepare_rotation

    key = tmp_path / "keys.json"
    key.write_text(json.dumps({"version": 1, "keys": [Fernet.generate_key().decode()]}))
    key.chmod(0o600)
    monkeypatch.setenv("BS_SECRET_KEYS_FILE", str(key))
    get_keyring.cache_clear()
    manifest = {"version": 1}
    for name in ("mysql", "redis", "minio", "elasticsearch", "milvus"):
        p = tmp_path / (name + ".password")
        p.write_text(secrets.token_urlsafe(24) + "@:$#%'\\\"")
        p.chmod(0o600)
        manifest[name] = {"secret_key_file" if name == "minio" else "password_file": p.name}
    user = tmp_path / "minio.user"
    user.write_text("rotation-test-user")
    user.chmod(0o600)
    manifest["minio"]["access_key_file"] = user.name
    inputs = tmp_path / "fresh.yaml"
    inputs.write_text(yaml.safe_dump(manifest))
    env = tmp_path / "deployment.env"
    env.write_text("BISHENG_GATEWAY_HMAC_SECRET=\nCOMPOSE_PROJECT_NAME=e2e-rotation\n")
    env.chmod(0o600)
    root = Path(__file__).resolve().parents[4]
    base = tmp_path / "bundle"
    prepare_bundle(
        config=root / "docker/bisheng/config/config.yaml",
        inputs=inputs,
        key_file=key,
        out_dir=base,
        env_file=env,
    )
    monkeypatch.setenv("BS_CREDENTIAL_DEPLOYMENT_ID", json.loads((base / "manifest.json").read_text())["deployment_id"])

    def create(selected=("mysql", "redis"), out=None, **kwargs):
        change = {"version": 1}
        for name in selected:
            p = tmp_path / ("new-" + name + ".password")
            p.write_text(secrets.token_urlsafe(24) + "@:$#%'\\\"")
            p.chmod(0o600)
            change[name] = {"secret_key_file" if name == "minio" else "password_file": p.name}
        request = tmp_path / "change.yaml"
        request.write_text(yaml.safe_dump(change))
        request.chmod(0o600)
        return prepare_rotation(
            base_bundle=base, key_file=key, inputs=request, out_dir=out or tmp_path / "rotation", env_file=env, **kwargs
        )

    yield create, base, key, env
    get_keyring.cache_clear()


def test_plan_has_only_selected_targets_and_preserves_source(rotation_deployment):
    from bisheng.core.config.credential_rotation import read_journal, read_plan

    create, base, key, _ = rotation_deployment
    before = {str(p.relative_to(base)): p.read_bytes() for p in base.rglob("*") if p.is_file()}
    key_before = key.read_bytes()
    session = create()
    plan = read_plan(session)
    assert plan["selected"] == ["mysql", "redis"]
    assert plan["version"] == 1
    assert key.read_bytes() == key_before
    assert before == {str(p.relative_to(base)): p.read_bytes() for p in base.rglob("*") if p.is_file()}
    assert read_journal(session)["phase"] == "PREPARED"
    assert plan["stages"]["mysql"] != plan["stages"]["redis"]
    last = Path(plan["stages"]["redis"])
    assert bundle_native_files(last, key)["minio.password"] == bundle_native_files(base, key)["minio.password"]
    assert (session.stat().st_mode & 0o777) == 0o700
    assert (session / "plan.json").stat().st_mode & 0o077 == 0
    for p in (session / "inputs").glob("*.password"):
        assert p.read_text() not in (session / "plan.json").read_text()


@pytest.mark.parametrize(
    "new,old,expected",
    [
        ("OK", "DENIED", "PERSIST"),
        ("DENIED", "OK", "APPLY"),
        ("OK", "OK", "DUAL"),
        ("UNKNOWN", "OK", "STOP"),
        ("DENIED", "DENIED", "STOP"),
    ],
)
def test_resume_requires_authentication_specific_evidence(new, old, expected):
    from bisheng.core.config.credential_rotation import resume_decision

    assert resume_decision(new, old) == expected


def test_progress_cannot_skip_unverified_native_or_previous_target(rotation_deployment):
    from bisheng.core.config.credential_rotation import mark_phase, read_journal, record_component

    create, _, _, _ = rotation_deployment
    session = create()
    with pytest.raises(CredentialConfigurationError):
        record_component(session, "mysql", "CHANGE_INTENT")
    with pytest.raises(CredentialConfigurationError):
        mark_phase(session, "COMPLETE")
    for phase in ("PREFLIGHT_OK", "MAINTENANCE_CONFIRMED", "CONSUMERS_STOPPED"):
        mark_phase(session, phase)
    with pytest.raises(CredentialConfigurationError):
        record_component(session, "redis", "CHANGE_INTENT")
    with pytest.raises(CredentialConfigurationError):
        record_component(session, "mysql", "FILES_PERSISTED")
    for phase in ("CHANGE_INTENT", "NATIVE_VERIFIED", "FILES_PERSISTED"):
        record_component(session, "mysql", phase)
        record_component(session, "mysql", phase)
    record_component(session, "redis", "CHANGE_INTENT")
    assert read_journal(session)["components"]["mysql"]["phase"] == "FILES_PERSISTED"


def test_unchanged_password_is_rejected_before_any_plan_activation(rotation_deployment, tmp_path):
    from bisheng.core.config.credential_rotation import prepare_rotation

    _, base, key, env = rotation_deployment
    p = tmp_path / "same.yaml"
    password = tmp_path / "same-password.sealed"
    write_confidential(password, bundle_native_files(base, key)["mysql.password"], key_file=key)
    p.write_text(yaml.safe_dump({"version": 1, "mysql": {"password_file": str(password)}}))
    out = tmp_path / "same-plan"
    with pytest.raises(CredentialConfigurationError, match="unchanged"):
        prepare_rotation(base_bundle=base, key_file=key, inputs=p, out_dir=out, env_file=env)
    assert not out.exists()


def test_corrupt_or_replaced_stage_cannot_resume(rotation_deployment):
    from bisheng.core.config.credential_rotation import read_plan

    create, _, _, _ = rotation_deployment
    session = create()
    plan = read_plan(session)
    (Path(plan["stages"]["mysql"]) / "mysql.password").write_text("unknown-third-value")
    with pytest.raises(CredentialConfigurationError):
        read_plan(session)


def test_existing_plan_directory_is_not_overwritten(rotation_deployment, tmp_path):
    create, _, _, _ = rotation_deployment
    session = create()
    before = (session / "plan.json").read_bytes()
    with pytest.raises(CredentialConfigurationError):
        create(out=session)
    assert (session / "plan.json").read_bytes() == before


def test_journal_disk_failure_leaves_last_durable_checkpoint(rotation_deployment, monkeypatch):
    from bisheng.core.config import credential_rotation as mod

    create, _, _, _ = rotation_deployment
    session = create()
    for phase in ("PREFLIGHT_OK", "MAINTENANCE_CONFIRMED", "CONSUMERS_STOPPED"):
        mod.mark_phase(session, phase)
    before = (session / "journal.json").read_bytes()
    monkeypatch.setattr(mod.os, "fsync", lambda fd: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(CredentialConfigurationError):
        mod.record_component(session, "mysql", "CHANGE_INTENT")
    assert (session / "journal.json").read_bytes() == before


def test_same_key_backup_path_can_restore_but_new_key_cannot(rotation_deployment, tmp_path):
    from bisheng.core.config.credential_rotation import read_plan

    create, _, key, _ = rotation_deployment
    session = create()
    backup = tmp_path / "backup-key.json"
    backup.write_bytes(key.read_bytes())
    backup.chmod(0o600)
    key.unlink()
    assert read_plan(session, key_file=backup)["key_file"] == str(backup)
    backup.write_text(json.dumps({"version": 1, "keys": [Fernet.generate_key().decode()]}))
    with pytest.raises(CredentialConfigurationError):
        read_plan(session, key_file=backup)


def test_prepare_writes_plaintext_redis_conf_for_option_c(rotation_deployment, tmp_path, monkeypatch):
    from bisheng.core.config import credential_rotation as state
    from bisheng.core.config import credential_rotation_compose as compiler

    create, _, _, _ = rotation_deployment
    inventory = tmp_path / "inventory.json"
    state.atomic_json(inventory, {"capabilities": {"redis": {"username": "default"}}, "native_files": {}})
    monkeypatch.setattr(
        compiler,
        "compile_native",
        lambda *a, **k: {
            "redis_conf": "appendonly yes\nmaxmemory-policy noeviction\n",
            "compose": {"services": {}},
            "services": ["redis"],
            "images": {},
        },
    )
    session = create(("redis",), inventory_file=inventory, installer_root="/docker")
    conf = session / "native" / "redis.conf"
    assert conf.read_text() == "appendonly yes\nmaxmemory-policy noeviction\n"
    assert b"bisheng.credentials.v2" not in conf.read_bytes()


def test_explicit_paired_rollback_restores_original_password_and_binds_request(
    rotation_deployment, tmp_path, monkeypatch
):
    from bisheng.core.config import credential_rotation as state
    from bisheng.core.config import credential_rotation_compose as compiler
    from bisheng.core.config.credential_tool import check_bundle

    create, base, key, env = rotation_deployment
    inventory = tmp_path / "inventory.json"
    state.atomic_json(inventory, {"capabilities": {"redis": {"username": "default"}}, "native_files": {}})
    monkeypatch.setattr(
        compiler,
        "compile_native",
        lambda *a, **k: {"redis_conf": None, "compose": {"services": {}}, "services": ["redis"], "images": {}},
    )
    session = create(("redis",), inventory_file=inventory)
    state.mark_phase(session, "PREFLIGHT_OK")
    state.mark_phase(session, "MAINTENANCE_CONFIRMED")
    state.mark_phase(session, "CONSUMERS_STOPPED")
    state.record_component(session, "redis", "CHANGE_INTENT")
    rollback = state.prepare_rollback(session, out_dir=tmp_path / "rollback", key_file=key, installer_root="/docker")
    reverse = state.read_plan(rollback)
    forward = state.read_plan(session)
    old = state.credentials(check_bundle(base, env_file=env)[0])
    restored = state.credentials(check_bundle(reverse["stages"]["redis"], env_file=env)[0])
    assert restored == old
    assert reverse["rollback_of"] == forward["run_id"]
    assert reverse["request_digest"] == forward["request_digest"]
    assert state.read_journal(session)["phase"] == "CHANGING"


def test_all_stage_native_artifacts_are_checked_before_publishing_plan(rotation_deployment, tmp_path):
    from bisheng.core.config import credential_rotation as state

    create, base, key, _ = rotation_deployment
    captured = yaml.safe_load(bundle_native_files(base, key)["milvus.yaml"])
    captured["common"]["security"]["authorizationEnabled"] = False
    inventory = tmp_path / "bad-native.json"
    state.atomic_json(
        inventory, {"native_files": {"milvus.yaml": yaml.safe_dump(captured)}, "milvus_auth_enabled": False}
    )
    before = (base / "milvus.yaml").read_bytes()
    with pytest.raises(CredentialConfigurationError, match="milvus"):
        create(("mysql",), inventory_file=inventory)
    assert not (tmp_path / "rotation").exists()
    assert (base / "milvus.yaml").read_bytes() == before
