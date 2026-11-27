"""Security-disabled upgrades preserve existing identities and frozen indexes."""

import io
import json
import shutil
from contextlib import contextmanager
from unittest.mock import Mock

import pytest
import yaml

from bisheng.core.config import credential_es_migration as es
from bisheng.core.config.credential_artifact_cli import seal_input_value
from bisheng.core.config.credential_artifacts import bundle_native_files, read_confidential
from bisheng.core.config.credential_sealed_migration import prepare_migration, status, verify_staged
from bisheng.core.config.secret_crypto import CredentialConfigurationError
from test.core.test_credential_sealed_bundle import sealed_deployment as sealed_deployment
from test.core.test_credential_sealed_migration import legacy as legacy


@pytest.fixture
def unauthenticated(legacy):
    source, store, key, values = legacy
    config = source / "config.yaml"
    data = yaml.safe_load(config.read_bytes())
    data["vector_stores"]["elasticsearch"]["ssl_verify"].pop("basic_auth", None)
    config.write_text(yaml.safe_dump(data))
    (source / "elasticsearch.password").write_bytes(b"")
    return source, store, key, values


def make_session(legacy, mode="enable"):
    source, store, key, _ = legacy
    inputs = None
    if mode != "retain":
        folder = store / "es-input"
        folder.mkdir(mode=0o700)
        (folder / ".artifact-context.json").write_text(
            json.dumps({"version": 2, "revision": "a" * 32, "deployment_id": "migration-deployment"})
        )
        (folder / ".artifact-context.json").chmod(0o600)
        seal_input_value(
            b"654321",
            folder / "es.password",
            key_file=key,
            deployment="migration-deployment",
            component="elasticsearch",
        )
        inputs = folder / "inputs.yaml"
        inputs.write_text("version: 1\nelasticsearch:\n  password_file: es.password\n")
    return prepare_migration(
        source,
        store=store,
        key_file=key,
        out_dir=store / "migrations/es-test",
        deployment="migration-deployment",
        es_mode=mode,
        inputs=inputs,
    )


def client(security=False, anonymous=False):
    value = Mock()
    value.info.return_value = {"version": {"number": "8.12.0"}, "cluster_uuid": "original-cluster"}
    value.xpack.info.return_value = {"features": {"security": {"enabled": security}}}
    value.nodes.info.return_value = {"nodes": {"node-1": {}}}
    value.security.authenticate.return_value = {
        "username": "_anonymous" if anonymous else "elastic",
        "authentication_type": "anonymous" if anonymous else "realm",
    }
    value.indices.get.return_value = {
        "customer": {"settings": {"index": {"uuid": "original-index"}}, "aliases": {"search": {}}}
    }
    value.indices.stats.return_value = {"indices": {"customer": {"primaries": {"docs": {"count": 7}}}}}
    value.get.return_value = {"_source": {"credential_migration_probe": True}}
    return value


def use_client(monkeypatch, value):
    @contextmanager
    def connection(*args):
        yield value

    monkeypatch.setattr(es, "_es", connection)


def test_server_security_settings_distinguish_disabled_and_anonymous():
    assert es.security_state(client()) == "DISABLED"
    assert es.security_state(client(security=True)) == "AUTHENTICATED"
    with pytest.raises(CredentialConfigurationError, match="anonymous"):
        es.security_state(client(security=True, anonymous=True))


def test_unknown_and_multinode_are_not_guessed_disabled():
    value = client()
    value.xpack.info.return_value = {}
    with pytest.raises(CredentialConfigurationError, match="unknown"):
        es.security_state(value)
    value = client()
    value.nodes.info.return_value = {"nodes": {"a": {}, "b": {}}}
    with pytest.raises(CredentialConfigurationError, match="topology"):
        es.security_state(value)


@pytest.mark.parametrize("mode", ["enable", "retain", "recover"])
def test_prepared_transition_preserves_other_credentials_and_encrypts_material(unauthenticated, mode):
    source, _, key, values = unauthenticated
    session = make_session(unauthenticated, mode)
    verify_staged(session, session / "bundle", key_file=key)
    native = bundle_native_files(session / "bundle", key)
    assert native["mysql.password"].decode() == values["mysql"]
    assert native["elasticsearch.password"] == (b"" if mode == "retain" else b"654321")
    # Option C keeps native password files as host plaintext; sealed/journal must not.
    allow = {".password", ".user", ".acl", ".cnf", ".yaml", ".yml", ".env", ".conf"}
    for p in session.rglob("*"):
        if p.is_file() and p.suffix not in allow and p.name != "openfga.env":
            assert b"654321" not in p.read_bytes()
    assert (source / "mysql.password").exists()


def test_freeze_is_immutable_and_reset_requires_explicit_retry(unauthenticated, monkeypatch):
    _, _, key, _ = unauthenticated
    session = make_session(unauthenticated)
    value = client()
    use_client(monkeypatch, value)
    es.freeze(session, key)
    baseline = status(session, key_file=key)["es"]["baseline"]
    es.freeze(session, key)
    assert value.indices.stats.call_count == 1
    assert status(session, key_file=key)["es"]["baseline"] == baseline
    assert json.loads(read_confidential(session / baseline["file"], key_file=key))["indexes"]["customer"]["count"] == 7
    es.reset_intent(session, key)
    with pytest.raises(CredentialConfigurationError, match="uncertain"):
        es.reset_intent(session, key)
    es.reset_intent(session, key, retry=True)


def test_changed_index_blocks_success_before_probe_write(unauthenticated, monkeypatch):
    _, _, key, _ = unauthenticated
    session = make_session(unauthenticated)
    value = client()
    use_client(monkeypatch, value)
    es.freeze(session, key)
    value.xpack.info.return_value = {"features": {"security": {"enabled": True}}}
    es.reset_intent(session, key)
    es.persist_password(session, key)
    value.indices.stats.return_value["indices"]["customer"]["primaries"]["docs"]["count"] = 8
    with pytest.raises(CredentialConfigurationError, match="original indexes"):
        es.verify(session, key)
    value.indices.create.assert_not_called()


def test_index_stats_can_arrive_after_http_security_ready(monkeypatch):
    value = client()
    full = value.indices.stats.return_value
    value.indices.stats.side_effect = [{"indices": {}}, full]
    monkeypatch.setattr(es.time, "sleep", lambda _: None)
    assert es.index_baseline(value, recovery_seconds=60)["indexes"]["customer"]["uuid"] == "original-index"
    assert value.indices.stats.call_count == 2


def test_customer_dot_security_name_is_not_skipped():
    value = client()
    value.indices.get.return_value[".security-customer"] = {
        "settings": {"index": {"uuid": "customer-owned-dot-index"}},
        "aliases": {},
    }
    value.indices.stats.return_value["indices"][".security-customer"] = {"primaries": {"docs": {"count": 2}}}
    assert es.index_baseline(value)["indexes"][".security-customer"]["uuid"] == "customer-owned-dot-index"
    value.info.return_value["cluster_uuid"] = "_na_"
    with pytest.raises(CredentialConfigurationError, match="cluster identity"):
        es.index_baseline(value)


def test_security_enable_datastream_indexes_are_excluded_from_baseline():
    value = client()
    stream = ".ds-.logs-deprecation.elasticsearch-default-2026.11.15-000001"
    value.indices.get.return_value[stream] = {
        "settings": {"index": {"uuid": "deprecation-stream"}},
        "aliases": {},
    }
    value.indices.stats.return_value["indices"][stream] = {"primaries": {"docs": {"count": 1}}}
    baseline = es.index_baseline(value)
    assert stream not in baseline["indexes"]
    assert "customer" in baseline["indexes"]


def test_retain_is_verified_without_adding_authentication(unauthenticated, monkeypatch):
    _, _, key, _ = unauthenticated
    session = make_session(unauthenticated, "retain")
    use_client(monkeypatch, client())
    es.freeze(session, key)
    es.verify(session, key)
    assert status(session, key_file=key)["es"]["phase"] == "VERIFIED"
    assert es.observe_target(session, key) == "KEEP"


def test_interrupted_probe_is_removed_only_with_matching_ownership(unauthenticated, monkeypatch):
    _, _, key, _ = unauthenticated
    session = make_session(unauthenticated, "retain")
    value = client()
    use_client(monkeypatch, value)
    es.freeze(session, key)
    value.index.side_effect = TimeoutError("simulated interruption")
    with pytest.raises(TimeoutError):
        es.verify(session, key)
    pending = status(session, key_file=key)["es"]["probe"]
    assert pending["name"].startswith("bisheng-credential-probe-")
    assert value.indices.create.call_args.kwargs["mappings"]["_meta"]["bisheng_credential_probe"] == pending["token"]

    value.indices.get.side_effect = lambda **kwargs: (
        {pending["name"]: {"mappings": {"_meta": {"bisheng_credential_probe": "other-owner"}}}}
        if kwargs["index"] == pending["name"]
        else {"customer": {"settings": {"index": {"uuid": "original-index"}}, "aliases": {"search": {}}}}
    )
    with pytest.raises(CredentialConfigurationError, match="ownership"):
        es.verify(session, key)
    value.indices.delete.assert_not_called()
    assert status(session, key_file=key)["es"]["probe"] == pending

    value.indices.get.side_effect = lambda **kwargs: (
        {pending["name"]: {"mappings": {"_meta": {"bisheng_credential_probe": pending["token"]}}}}
        if kwargs["index"] == pending["name"]
        else {"customer": {"settings": {"index": {"uuid": "original-index"}}, "aliases": {"search": {}}}}
    )
    value.index.side_effect = None
    es.verify(session, key)
    assert value.indices.delete.call_args_list[0].kwargs["index"] == pending["name"]
    assert status(session, key_file=key)["es"].get("probe") is None


def test_missing_native_adoption_is_reconstructed_as_plaintext_native(unauthenticated):
    source, _, key, _ = unauthenticated
    manifest = json.loads((source / "manifest.json").read_text())
    for name in manifest["native_files"]:
        (source / name).unlink()
    manifest.update(mode="adopt-key", native_files=[])
    (source / "manifest.json").write_text(json.dumps(manifest))
    session = make_session(unauthenticated)
    verify_staged(session, session / "bundle", key_file=key)
    # Option C: reconstructed native files are host plaintext, not sealed sidecars.
    assert (session / "bundle/mysql.password").exists()
    assert not list((session / "bundle").glob("native/*.sealed.json"))
    assert bundle_native_files(session / "bundle", key)["elasticsearch.password"] == b"654321"


def test_new_delivery_imports_old_bundle_without_cleaning_external_files(unauthenticated, tmp_path):
    source, store, key, _ = unauthenticated
    external = tmp_path / "old-delivery" / "bundle"
    shutil.copytree(source, external)
    session = prepare_migration(
        external,
        store=store,
        key_file=key,
        out_dir=store / "migrations/external-import",
        deployment="migration-deployment",
        es_mode="retain",
        allow_external_source=True,
    )
    verify_staged(session, session / "bundle", key_file=key)
    inventory = json.loads(read_confidential(session / "inventory.sealed.json", key_file=key))
    assert inventory["external_backups"]
    assert all(not item["path"].startswith(str(external)) for item in inventory["files"])
    assert (external / "config.yaml").exists()


def test_retained_no_auth_v2_can_later_enable_in_same_installer(unauthenticated):
    _, store, key, _ = unauthenticated
    retained = make_session(unauthenticated, "retain")
    source = retained / "bundle"
    assert json.loads((source / "manifest.json").read_text())["es_security_enabled"] is False
    folder = store / "later-es-input"
    folder.mkdir(mode=0o700)
    (folder / ".artifact-context.json").write_text(
        json.dumps({"version": 2, "revision": "a" * 32, "deployment_id": "migration-deployment"})
    )
    (folder / ".artifact-context.json").chmod(0o600)
    seal_input_value(
        b"654321", folder / "es.password", key_file=key, deployment="migration-deployment", component="elasticsearch"
    )
    (folder / "inputs.yaml").write_text("version: 1\nelasticsearch:\n  password_file: es.password\n")
    later = prepare_migration(
        source,
        store=store,
        key_file=key,
        out_dir=store / "migrations/later-enable",
        deployment="migration-deployment",
        es_mode="enable",
        inputs=folder / "inputs.yaml",
    )
    verify_staged(later, later / "bundle", key_file=key)
    assert json.loads((later / "bundle/manifest.json").read_text())["es_security_enabled"] is True
    assert bundle_native_files(later / "bundle", key)["elasticsearch.password"] == b"654321"


def test_bootstrap_login_is_not_a_native_password_checkpoint(unauthenticated, monkeypatch):
    _, _, key, _ = unauthenticated
    session = make_session(unauthenticated)
    value = client()
    use_client(monkeypatch, value)
    es.freeze(session, key)
    value.xpack.info.return_value = {"features": {"security": {"enabled": True}}}
    assert es.observe_target(session, key) == "READY"
    with pytest.raises(CredentialConfigurationError, match="bootstrap"):
        es.verify(session, key)
    es.reset_intent(session, key)
    value.security.change_password.side_effect = TimeoutError("password must never be logged")
    with pytest.raises(TimeoutError):
        es.persist_password(session, key)
    assert status(session, key_file=key)["es"]["phase"] == "PASSWORD_INTENT"


def inspection():
    return [
        {
            "Name": "/customer-es",
            "Image": "sha256:" + "c" * 64,
            "Config": {
                "Labels": {"com.docker.compose.project": "customer", "com.docker.compose.service": "elasticsearch"},
                "Env": ["ELASTICSEARCH_ENABLE_SECURITY=false", "ELASTICSEARCH_PASSWORD=old-unlogged-value"],
                "Cmd": ["/opt/bitnami/scripts/elasticsearch/run.sh"],
                "User": "1001",
                "Hostname": "customer-es",
            },
            "HostConfig": {
                "Memory": 1073741824,
                "PortBindings": {"9200/tcp": [{"HostIp": "127.0.0.1", "HostPort": "19200"}]},
            },
            "Mounts": [
                {
                    "Type": "bind",
                    "Source": "/customer/es/data",
                    "Destination": "/bitnami/elasticsearch/data",
                    "RW": True,
                }
            ],
            "NetworkSettings": {"Networks": {"customer-network": {"Aliases": ["customer-es", "elasticsearch"]}}},
        }
    ]


@pytest.mark.parametrize("user", ["1001", "2345:3456", "0:0", ""])
def test_native_export_preserves_actual_data_ports_and_resources(unauthenticated, monkeypatch, user):
    _, _, key, _ = unauthenticated
    session = make_session(unauthenticated)
    use_client(monkeypatch, client())
    es.freeze(session, key)
    captured = inspection()
    captured[0]["Config"]["User"] = user
    compiled = es.compile_es(session, key, io.StringIO(json.dumps(captured)), "0")
    service = compiled["services"]["elasticsearch"]
    assert service.get("user") == (user or None)
    assert service["image"] == inspection()[0]["Image"]
    assert service["mem_limit"] == 1073741824
    assert service["ports"][0]["published"] == "19200"
    assert any(v.get("source") == "/customer/es/data" for v in service["volumes"] if isinstance(v, dict))
    assert service["environment"]["ELASTICSEARCH_ENABLE_SECURITY"] == "true"
    assert "old-unlogged-value" not in json.dumps(compiled)
    ref = status(session, key_file=key)["es"]["runtime"]
    assert b"old-unlogged-value" not in (session / ref["file"]).read_bytes()


def test_native_capture_rejects_an_unrelated_endpoint(unauthenticated, monkeypatch):
    _, _, key, _ = unauthenticated
    session = make_session(unauthenticated)
    use_client(monkeypatch, client())
    es.freeze(session, key)
    captured = inspection()
    captured[0]["NetworkSettings"]["Networks"]["customer-network"]["Aliases"] = ["unrelated"]
    with pytest.raises(CredentialConfigurationError, match="endpoint"):
        es.compile_es(session, key, io.StringIO(json.dumps(captured)), "0")


def test_paired_return_keeps_data_and_original_missing_auth(unauthenticated, monkeypatch):
    _, _, key, values = unauthenticated
    session = make_session(unauthenticated)
    use_client(monkeypatch, client())
    es.freeze(session, key)
    es.compile_es(session, key, io.StringIO(json.dumps(inspection())), "0")
    es.reset_intent(session, key)
    es.prepare_rollback(session, key)
    value = status(session, key_file=key)
    target = value["bundle"]
    verify_staged(session, target, key_file=key)
    native = bundle_native_files(target, key)
    assert native["elasticsearch.password"] == b""
    assert native["mysql.password"].decode() == values["mysql"]
    assert es.credentials(es.settings_for(target))["elasticsearch"] == ""
    assert (
        es.export_es(session, key)["services"]["elasticsearch"]["environment"]["ELASTICSEARCH_ENABLE_SECURITY"]
        == "false"
    )
    assert value["es"]["mode"] == "retain"
