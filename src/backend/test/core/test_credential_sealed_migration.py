"""Legacy plaintext is backed up as ciphertext before any cleanup is allowed."""

import json
import stat

import pytest
import yaml

from bisheng.core.config.credential_artifacts import bundle_native_files, read_confidential
from bisheng.core.config.credential_bundle import prepare_bundle
from bisheng.core.config.credential_sealed_migration import (
    cleanup,
    mark_phase,
    prepare_migration,
    sanitize_environment,
    verify_bindings,
    verify_staged,
)
from bisheng.core.config.secret_crypto import CredentialConfigurationError, get_keyring
from test.core.test_credential_sealed_bundle import sealed_deployment as _sealed_deployment
from test.core.test_credential_sealed_rotation import assert_private_native_bundle

# Re-export the fixture without shadowing an imported binding in test parameters.
sealed_deployment = _sealed_deployment


@pytest.fixture
def legacy(sealed_deployment, tmp_path, monkeypatch):
    args, values = sealed_deployment
    v2 = prepare_bundle(**args)
    store = tmp_path / "store"
    source = store / "revisions/old/bundle"
    source.mkdir(mode=0o700, parents=True)
    native = bundle_native_files(v2, args["key_file"])
    for name, value in native.items():
        p = source / name
        p.write_bytes(value)
        p.chmod(0o600)
    (source / "config.yaml").write_bytes((v2 / "config.yaml").read_bytes())
    (source / "config.yaml").chmod(0o600)
    m = json.loads((v2 / "manifest.json").read_text())
    for name in ["roles", "native_sha256", "deployment_id", "runtime_seeded"]:
        m.pop(name, None)
    m["version"] = 1
    (source / "manifest.json").write_text(json.dumps(m))
    (source / "manifest.json").chmod(0o600)
    (store / "migrations").mkdir()
    (store / "deployment.id").write_text("migration-deployment\n")
    (store / "deployment.id").chmod(0o600)
    monkeypatch.setenv("BS_SECRET_KEYS_FILE", str(args["key_file"]))
    monkeypatch.delenv("BS_CREDENTIAL_DEPLOYMENT_ID", raising=False)
    get_keyring.cache_clear()
    yield source, store, args["key_file"], values
    get_keyring.cache_clear()


def test_conversion_preserves_values_and_does_not_delete_source_before_switch(legacy):
    source, store, key, values = legacy
    session = prepare_migration(
        source, store=store, key_file=key, out_dir=store / "migrations/test", deployment="migration-deployment"
    )
    assert (source / "mysql.password").read_text() == values["mysql"]
    native = bundle_native_files(session / "bundle", key)
    assert native["mysql.password"].decode() == values["mysql"]
    allowed = assert_private_native_bundle(session / "bundle", key)
    for name, content in native.items():
        assert content == bundle_native_files(source, key, allow_legacy=True)[name]
    for p in session.rglob("*"):
        if p.is_dir():
            assert not p.is_symlink() and stat.S_IMODE(p.stat().st_mode) == 0o700
        elif p.is_file() and p not in allowed:
            assert not any(v.encode() in p.read_bytes() for v in values.values()), str(p.relative_to(session))
    assert read_confidential(session / "inventory.sealed.json", key_file=key)
    with pytest.raises(CredentialConfigurationError):
        cleanup(session, key_file=key)


def test_cleanup_only_after_verified_switch_and_detects_modified_source(legacy):
    source, store, key, _ = legacy
    session = prepare_migration(
        source, store=store, key_file=key, out_dir=store / "migrations/test", deployment="migration-deployment"
    )
    verify_staged(session, session / "bundle", key_file=key)
    mark_phase(session, "CONSUMERS_SWITCHED")
    (source / "mysql.password").write_text("unexpected-concurrent-change")
    with pytest.raises(CredentialConfigurationError):
        cleanup(session, key_file=key)
    assert (source / "mysql.password").read_text() == "unexpected-concurrent-change"


def test_cleanup_removes_owned_legacy_files_but_retains_encrypted_backups(legacy):
    source, store, key, _ = legacy
    external = store.parent / "customer-original"
    external.write_text("unrelated-customer-file")
    session = prepare_migration(
        source, store=store, key_file=key, out_dir=store / "migrations/test", deployment="migration-deployment"
    )
    verify_staged(session, session / "bundle", key_file=key)
    mark_phase(session, "CONSUMERS_SWITCHED")
    cleanup(session, key_file=key)
    assert not (source / "mysql.password").exists()
    assert external.read_text() == "unrelated-customer-file"
    assert list((session / "backups").glob("*.sealed"))
    assert json.loads((session / "journal.json").read_text())["phase"] == "COMPLETE"


def test_cleanup_cannot_treat_an_unmounted_store_as_deleted_files(legacy):
    source, store, key, _ = legacy
    session = prepare_migration(
        source, store=store, key_file=key, out_dir=store / "migrations/test", deployment="migration-deployment"
    )
    verify_staged(session, session / "bundle", key_file=key)
    mark_phase(session, "CONSUMERS_SWITCHED")
    (store / "deployment.id").unlink()
    with pytest.raises(CredentialConfigurationError):
        cleanup(session, key_file=key)
    assert (source / "mysql.password").exists()
    assert json.loads((session / "journal.json").read_text())["phase"] == "CONSUMERS_SWITCHED"


def test_cleanup_preserves_an_active_key_even_inside_the_old_bundle(legacy):
    source, store, original_key, _ = legacy
    key = source / "active-master.json"
    key.write_bytes(original_key.read_bytes())
    key.chmod(0o600)
    session = prepare_migration(
        source, store=store, key_file=key, out_dir=store / "migrations/test", deployment="migration-deployment"
    )
    verify_staged(session, session / "bundle", key_file=key)
    mark_phase(session, "CONSUMERS_SWITCHED", key_file=key)
    verify_bindings(session, [str(key), str(session / "bundle")], key_file=key)
    cleanup(session, key_file=key)
    assert key.read_bytes() == original_key.read_bytes()
    assert not (source / "mysql.password").exists()


def test_cleanup_cli_requires_the_whole_managed_store_mount(legacy):
    from bisheng.core.config.credential_tool import main

    source, store, key, _ = legacy
    session = prepare_migration(
        source, store=store, key_file=key, out_dir=store / "migrations/test", deployment="migration-deployment"
    )
    verify_staged(session, session / "bundle", key_file=key)
    mark_phase(session, "CONSUMERS_SWITCHED")
    assert (
        main(
            [
                "artifact",
                "migrate-clean",
                "--session-dir",
                str(session),
                "--key-file",
                str(key),
                "--deployment-id",
                "migration-deployment",
            ]
        )
        == 2
    )
    assert (source / "mysql.password").exists()


def test_live_or_stopped_legacy_directory_bindings_block_cleanup(legacy):
    source, store, key, _ = legacy
    session = prepare_migration(
        source, store=store, key_file=key, out_dir=store / "migrations/test", deployment="migration-deployment"
    )
    for bindings in [[], [str(source)], [str(source / "mysql.password")], [str(store)]]:
        with pytest.raises(CredentialConfigurationError):
            verify_bindings(session, bindings, key_file=key)
    verify_bindings(session, [str(session / "bundle"), str(key)], key_file=key)
    assert (source / "mysql.password").exists()


def test_consumed_env_passwords_are_removed_only_after_encrypted_backup(sealed_deployment, tmp_path):
    args, values = sealed_deployment
    bundle = prepare_bundle(**args)
    env = tmp_path / ".env"
    before = f"REDIS_PASSWORD={values['redis']}\nCOMPOSE_PROJECT_NAME=owned\nCUSTOM_ENDPOINT=https://example.invalid\n"
    env.write_text(before)
    env.chmod(0o600)
    session = tmp_path / "backup"
    sanitize_environment(bundle, env, session, key_file=args["key_file"])
    assert "REDIS_PASSWORD" not in env.read_text()
    assert "COMPOSE_PROJECT_NAME=owned" in env.read_text()
    assert read_confidential(session / "environment.before.sealed", key_file=args["key_file"]).decode() == before
    assert values["redis"].encode() not in (session / "environment.before.sealed").read_bytes()
    sanitize_environment(bundle, env, session, key_file=args["key_file"])


def test_shared_env_alias_refuses_cleanup_before_mutating_any_file(sealed_deployment, tmp_path):
    args, values = sealed_deployment
    bundle = prepare_bundle(**args)
    config = bundle / "config.yaml"
    config.write_text(config.read_text() + "\ncustomer_field: !env ${REDIS_PASSWORD}\n")
    env = tmp_path / ".env"
    env.write_text("REDIS_PASSWORD=" + values["redis"] + "\n")
    env.chmod(0o600)
    before = env.read_bytes()
    with pytest.raises(CredentialConfigurationError, match="another config consumer"):
        sanitize_environment(bundle, env, tmp_path / "backup", key_file=args["key_file"])
    assert env.read_bytes() == before
    assert not (tmp_path / "backup").exists()


def test_legacy_inputs_are_sealed_in_place_and_metadata_remains_usable(legacy):
    from bisheng.core.config.credential_inputs import read_secret

    source, store, key, values = legacy
    inputs = store / "inputs"
    inputs.mkdir(mode=0o700)
    password = inputs / "mysql.password"
    password.write_text(values["mysql"])
    password.chmod(0o600)
    manifest = inputs / "inputs.yaml"
    manifest.write_text("version: 1\nmysql:\n  password_file: mysql.password\n")
    manifest.chmod(0o600)
    # Keep an authenticated context available to other already-encrypted inputs.
    context = inputs / ".artifact-context.json"
    context.write_text(json.dumps({"version": 2, "revision": "a" * 32, "deployment_id": "migration-deployment"}))
    context.chmod(0o600)
    before = manifest.read_bytes(), context.read_bytes()
    session = prepare_migration(
        source, store=store, key_file=key, out_dir=store / "migrations/test", deployment="migration-deployment"
    )
    verify_staged(session, session / "bundle", key_file=key)
    mark_phase(session, "CONSUMERS_SWITCHED")
    cleanup(session, key_file=key)
    assert password.exists() and values["mysql"].encode() not in password.read_bytes()
    assert read_secret(password, allow_plaintext=False) == values["mysql"]
    assert (manifest.read_bytes(), context.read_bytes()) == before
    cleanup(session, key_file=key)
    assert read_secret(password, allow_plaintext=False) == values["mysql"]


def test_binding_cli_ignores_docker_separator_lines_but_not_missing_evidence(legacy, monkeypatch):
    import io
    import sys

    from bisheng.core.config.credential_tool import main

    source, store, key, _ = legacy
    session = prepare_migration(
        source, store=store, key_file=key, out_dir=store / "migrations/test", deployment="migration-deployment"
    )
    command = [
        "artifact",
        "migrate-bindings",
        "--key-file",
        str(key),
        "--session-dir",
        str(session),
        "--deployment-id",
        "migration-deployment",
    ]
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO((str(session / "bundle") + "\n\n").encode())))
    assert main(command) == 0
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"\n\n")))
    assert main(command) == 2


def test_unauthenticated_legacy_es_requires_explicit_in_installer_choice(legacy):
    source, store, key, _ = legacy
    config = source / "config.yaml"
    data = yaml.safe_load(config.read_bytes())
    data["vector_stores"]["elasticsearch"]["ssl_verify"].pop("basic_auth", None)
    config.write_text(yaml.safe_dump(data))
    (source / "elasticsearch.password").write_bytes(b"")
    out = store / "migrations/test"
    with pytest.raises(CredentialConfigurationError, match="explicit in-installer choice"):
        prepare_migration(source, store=store, key_file=key, out_dir=out, deployment="migration-deployment")
    assert not out.exists() and (source / "mysql.password").exists()
