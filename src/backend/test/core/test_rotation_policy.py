"""覆盖 AC: AC-49, AC-52, AC-56 — policy binds baseline, files and key identity."""

import json
from pathlib import Path

import pytest

from bisheng.core.config import credential_rotation as state
from bisheng.core.config.secret_crypto import CredentialConfigurationError
from test.core.test_credential_rotation import rotation_deployment as rotation_deployment


def completed(create):
    session = create(("redis",))
    state.mark_phase(session, "PREFLIGHT_OK")
    state.mark_phase(session, "MAINTENANCE_CONFIRMED")
    state.mark_phase(session, "CONSUMERS_STOPPED")
    for phase in ("CHANGE_INTENT", "NATIVE_VERIFIED", "FILES_PERSISTED"):
        state.record_component(session, "redis", phase)
    return session


def test_policy_cannot_activate_before_native_verification(rotation_deployment):
    create, _, _, _ = rotation_deployment
    session = create(("redis",))
    with pytest.raises(CredentialConfigurationError):
        state.write_deployment_policy(session)


def test_policy_roundtrip_and_bundle_tampering(rotation_deployment):
    create, _, key, env = rotation_deployment
    session = completed(create)
    target = state.write_deployment_policy(session)
    payload = state.validate_deployment_policy(target, key_file=key, env_file=env)
    assert payload["selected"] == ["redis"]
    assert payload["retained_pending"] == []
    assert payload["preserve_native"] is False
    (target / "config.yaml").write_text((target / "config.yaml").read_text() + "\n# tampered\n")
    with pytest.raises(CredentialConfigurationError, match="changed"):
        state.validate_deployment_policy(target, key_file=key, env_file=env)


def test_policy_signature_and_baseline_are_required(rotation_deployment):
    create, _, key, env = rotation_deployment
    session = completed(create)
    target = state.write_deployment_policy(session)
    policy = target / "deployment-policy.json"
    before = policy.read_text()
    data = json.loads(before)
    data["payload"]["retained_pending"] = ["mysql"]
    policy.write_text(json.dumps(data))
    with pytest.raises(CredentialConfigurationError, match="signature"):
        state.validate_deployment_policy(target, key_file=key, env_file=env)
    policy.write_text(before)
    baseline = Path(data["payload"]["baseline"]) / "manifest.json"
    baseline.write_text(baseline.read_text() + "\n")
    with pytest.raises(CredentialConfigurationError, match="baseline"):
        state.validate_deployment_policy(target, key_file=key, env_file=env)


def test_policy_allows_shrunk_pending_but_rejects_new_pending(rotation_deployment, tmp_path):
    import secrets

    import yaml
    from sqlalchemy.engine import make_url

    from bisheng.core.config.credential_bundle import prepare_bundle
    from bisheng.core.config.credential_loader import load_config
    from bisheng.core.config.secret_crypto import load_keyring

    create, base, key, env = rotation_deployment
    # Shrink: policy may retain historical pending that live rules no longer flag.
    session = completed(create)
    target = state.write_deployment_policy(session)
    policy = target / "deployment-policy.json"
    data = json.loads(policy.read_text())
    data["payload"]["retained_pending"] = ["mysql"]
    data["mac"] = state._policy_mac(data["payload"], key)
    policy.write_text(json.dumps(data))
    assert state.validate_deployment_policy(target, key_file=key, env_file=env)["retained_pending"] == ["mysql"]

    # Growth: live pending outside the freeze must still fail.
    source = tmp_path / "legacy.yaml"
    payload = load_config(base / "config.yaml", env_file=env).data
    payload["database_url"] = (
        make_url("mysql+pymysql://root@mysql:3306/bisheng")
        .set(password=load_keyring(key).encrypt("1234").decode())
        .render_as_string(hide_password=False)
    )
    source.write_text(yaml.safe_dump(payload))
    source.chmod(0o600)
    adopted = tmp_path / "adopted"
    prepare_bundle(mode="adopt-key", config=source, key_file=key, out_dir=adopted, env_file=env)
    password = tmp_path / "redis-next"
    password.write_text(secrets.token_urlsafe(25))
    password.chmod(0o600)
    request = tmp_path / "partial.yaml"
    request.write_text("version: 1\nredis:\n  password_file: redis-next\n")
    request.chmod(0o600)
    partial = state.prepare_rotation(
        base_bundle=adopted, key_file=key, inputs=request, out_dir=tmp_path / "partial", env_file=env
    )
    state.mark_phase(partial, "PREFLIGHT_OK")
    state.mark_phase(partial, "MAINTENANCE_CONFIRMED")
    state.mark_phase(partial, "CONSUMERS_STOPPED")
    for phase in ("CHANGE_INTENT", "NATIVE_VERIFIED", "FILES_PERSISTED"):
        state.record_component(partial, "redis", phase)
    final = state.write_deployment_policy(partial)
    document = json.loads((final / "deployment-policy.json").read_text())
    document["payload"]["retained_pending"] = []
    document["mac"] = state._policy_mac(document["payload"], key)
    (final / "deployment-policy.json").write_text(json.dumps(document))
    with pytest.raises(CredentialConfigurationError, match="scope"):
        state.validate_deployment_policy(final, key_file=key, env_file=env)


def test_unselected_weak_mysql_remains_explicitly_pending(rotation_deployment, tmp_path):
    import secrets

    import yaml

    from bisheng.core.config.credential_bundle import prepare_bundle
    from bisheng.core.config.credential_tool import check_bundle

    _, base, key, env = rotation_deployment
    source = tmp_path / "legacy.yaml"
    from bisheng.core.config.credential_loader import load_config

    data = load_config(base / "config.yaml", env_file=env).data
    from sqlalchemy.engine import make_url

    from bisheng.core.config.secret_crypto import load_keyring

    data["database_url"] = (
        make_url("mysql+pymysql://root@mysql:3306/bisheng")
        .set(password=load_keyring(key).encrypt("1234").decode())
        .render_as_string(hide_password=False)
    )
    source.write_text(yaml.safe_dump(data))
    source.chmod(0o600)
    adopted = tmp_path / "adopted"
    prepare_bundle(mode="adopt-key", config=source, key_file=key, out_dir=adopted, env_file=env)
    password = tmp_path / "redis-next"
    password.write_text(secrets.token_urlsafe(25))
    password.chmod(0o600)
    request = tmp_path / "partial.yaml"
    request.write_text("version: 1\nredis:\n  password_file: redis-next\n")
    request.chmod(0o600)
    session = state.prepare_rotation(
        base_bundle=adopted, key_file=key, inputs=request, out_dir=tmp_path / "partial", env_file=env
    )
    state.mark_phase(session, "PREFLIGHT_OK")
    state.mark_phase(session, "MAINTENANCE_CONFIRMED")
    state.mark_phase(session, "CONSUMERS_STOPPED")
    for phase in ("CHANGE_INTENT", "NATIVE_VERIFIED", "FILES_PERSISTED"):
        state.record_component(session, "redis", phase)
    final = state.write_deployment_policy(session)
    payload = state.validate_deployment_policy(final, key_file=key, env_file=env)
    assert payload["retained_pending"] == ["mysql"]
    assert payload["preserve_native"] is True
    settings, _, pending = check_bundle(final, enforce=True, env_file=env)
    assert pending == ["mysql"]
    assert "1234@" in settings.database_url
    # Next incremental plan validates the existing partial policy rather than
    # exempting arbitrary short credentials from deployment checks.
    password.write_text(secrets.token_urlsafe(25))
    next_session = state.prepare_rotation(
        base_bundle=final, key_file=key, inputs=request, out_dir=tmp_path / "next-partial", env_file=env
    )
    assert state.read_plan(next_session)["retained_pending"] == ["mysql"]
