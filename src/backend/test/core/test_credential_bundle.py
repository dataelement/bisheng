"""Configuration preparation behavior: AC-05/07/08/09/10/11/28/37."""

import json
import secrets
from pathlib import Path

import pytest
import yaml
from cryptography.fernet import Fernet
from sqlalchemy.engine import make_url

from bisheng.core.config.credential_bundle import prepare_bundle
from bisheng.core.config.secret_crypto import CredentialConfigurationError, load_keyring


@pytest.fixture
def deployment(tmp_path):
    keys = tmp_path / "keys.json"
    keys.write_text(json.dumps({"version": 1, "keys": [Fernet.generate_key().decode()]}))
    keys.chmod(0o600)
    values = {}
    for name in ("mysql", "redis", "minio", "elasticsearch", "milvus"):
        path = tmp_path / (name + ".password")
        path.write_text(secrets.token_urlsafe(24))
        path.chmod(0o600)
        values[name] = {"secret_key_file" if name == "minio" else "password_file": str(path)}
    user = tmp_path / "minio.user"
    user.write_text("minioadmin")
    values["minio"]["access_key_file"] = str(user)
    inputs = tmp_path / "inputs.yaml"
    inputs.write_text(yaml.safe_dump({"version": 1, **values}))
    config = tmp_path / "source.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "database_url": "mysql+pymysql://root:legacy@mysql:3306/bisheng?charset=utf8mb4",
                "redis_url": "redis://redis:6379/1",
                "celery_redis_url": "redis://redis:6379/2",
                "password_conf": {"max_error_times": 7},
                "object_storage": {
                    "type": "minio",
                    "minio": {"endpoint": "minio:9000", "access_key": "minioadmin", "secret_key": "legacy"},
                },
                "vector_stores": {
                    "milvus": {"connection_args": {"host": "milvus", "port": "19530", "secure": False}},
                    "elasticsearch": {"url": "http://elasticsearch:9200", "ssl_verify": {}},
                },
            }
        )
    )
    return {"config": config, "inputs": inputs, "key_file": keys, "out_dir": tmp_path / "bundle"}


def test_fresh_package_encrypts_business_config_and_keeps_native_credentials(deployment):
    original = deployment["config"].read_bytes()
    out = prepare_bundle(**deployment)
    conf = yaml.safe_load((out / "config.yaml").read_text())
    ring = load_keyring(deployment["key_file"])
    mysql = (out / "mysql.password").read_text()
    assert ring.decrypt(make_url(conf["database_url"]).password) == mysql
    minio = conf["object_storage"]["minio"]["secret_key"]
    assert ring.decrypt(minio[8:-1]) == (out / "minio.password").read_text()
    assert mysql not in (out / "config.yaml").read_text()
    assert conf["password_conf"]["max_error_times"] == 7
    assert deployment["config"].read_bytes() == original
    assert json.loads((out / "manifest.json").read_text())["pending"] == []
    assert (out.stat().st_mode & 0o777) == 0o700


def test_output_directory_never_overwritten(deployment):
    deployment["out_dir"].mkdir()
    marker = deployment["out_dir"] / "keep"
    marker.write_text("original")
    with pytest.raises(CredentialConfigurationError):
        prepare_bundle(**deployment)
    assert marker.read_text() == "original"


def test_new_weak_password_rejected_without_partial_activation(deployment):
    inputs = yaml.safe_load(deployment["inputs"].read_text())
    Path(inputs["mysql"]["password_file"]).write_text("1234")
    with pytest.raises(CredentialConfigurationError):
        prepare_bundle(**deployment)
    assert not deployment["out_dir"].exists()


def test_component_change_preserves_other_service_credentials(deployment, tmp_path):
    base = prepare_bundle(**deployment)
    old_mysql = (base / "mysql.password").read_bytes()
    old_login = yaml.safe_load((base / "milvus.yaml").read_text())["common"]["security"]["defaultRootPassword"]
    inputs = yaml.safe_load(deployment["inputs"].read_text())
    password = tmp_path / "new-minio.password"
    password.write_text(secrets.token_urlsafe(24))
    inputs["minio"]["secret_key_file"] = str(password)
    update = tmp_path / "update.yaml"
    update.write_text(yaml.safe_dump({"version": 1, "minio": inputs["minio"]}))
    out = prepare_bundle(
        mode="password-change",
        inputs=update,
        key_file=deployment["key_file"],
        out_dir=tmp_path / "next",
        base_bundle=base,
        component="minio",
    )
    assert (out / "mysql.password").read_bytes() == old_mysql
    native = yaml.safe_load((out / "milvus.yaml").read_text())
    assert native["common"]["security"]["defaultRootPassword"] == old_login
    assert native["minio"]["secretAccessKey"] == password.read_text()


def test_rotation_preserves_actual_passwords(deployment, tmp_path):
    base = prepare_bundle(**deployment)
    old = json.loads(deployment["key_file"].read_text())["keys"][0]
    new_keys = tmp_path / "new-keys.json"
    new_keys.write_text(json.dumps({"version": 1, "keys": [Fernet.generate_key().decode(), old]}))
    new_keys.chmod(0o600)
    out = prepare_bundle(mode="key-rotation", key_file=new_keys, out_dir=tmp_path / "next", base_bundle=base)
    assert (out / "mysql.password").read_bytes() == (base / "mysql.password").read_bytes()
    conf = yaml.safe_load((out / "config.yaml").read_text())
    assert (
        load_keyring(new_keys).decrypt_primary(make_url(conf["database_url"]).password)
        == (out / "mysql.password").read_text()
    )


def test_adopt_records_existing_insecure_state(deployment, tmp_path):
    ring = load_keyring(deployment["key_file"])
    config = yaml.safe_load(deployment["config"].read_text())
    config["database_url"] = (
        make_url(config["database_url"])
        .set(password=ring.encrypt("1234").decode())
        .render_as_string(hide_password=False)
    )
    config["object_storage"]["minio"]["secret_key"] = "minioadmin"
    deployment["config"].write_text(yaml.safe_dump(config))
    out = prepare_bundle(
        mode="adopt-key", config=deployment["config"], key_file=deployment["key_file"], out_dir=tmp_path / "adopt"
    )
    manifest = json.loads((out / "manifest.json").read_text())
    assert {"mysql", "redis", "minio", "milvus"} <= set(manifest["pending"])
    assert (out / "mysql.password").read_text() == "1234"
    assert not yaml.safe_load((out / "milvus.yaml").read_text())["common"]["security"]["authorizationEnabled"]


def test_shipped_template_can_prepare_without_legacy_secret_environment(deployment, tmp_path):
    root = Path(__file__).resolve().parents[4]
    deployment["config"] = root / "docker/bisheng/config/config.yaml"
    out = prepare_bundle(**deployment, environ={"BISHENG_GATEWAY_HMAC_SECRET": ""}, deployment_root=root / "docker")
    assert (out / "gateway-application.yml").exists()
    assert "encrypt(" in (out / "config.yaml").read_text()


def test_redis_rotation_preserves_custom_acl_permissions(deployment, tmp_path):
    base = prepare_bundle(**deployment)
    acl = base / "redis-users.acl"
    acl.write_text(
        acl.read_text().replace("~* &* +@all", "~tenant:* &events +get +set") + "user reader off ~read:* +get\n"
    )
    password = tmp_path / "new-redis"
    password.write_text("replacement-" + __import__("secrets").token_urlsafe(20))
    inputs = tmp_path / "change.yaml"
    inputs.write_text(yaml.safe_dump({"version": 1, "redis": {"password_file": str(password)}}))
    out = prepare_bundle(
        mode="password-change",
        component="redis",
        inputs=inputs,
        key_file=deployment["key_file"],
        base_bundle=base,
        out_dir=tmp_path / "next",
    )
    result = (out / "redis-users.acl").read_text()
    assert "~tenant:* &events +get +set" in result
    assert "user reader off ~read:* +get" in result
    assert "+@all" not in result


def test_redis_rotation_keeps_gateway_and_milvus_native_custom_settings(deployment, tmp_path):
    root = Path(__file__).resolve().parents[4]
    base = prepare_bundle(**deployment, deployment_root=root / "docker")
    password = tmp_path / "redis-new"
    password.write_text(secrets.token_urlsafe(24))
    inputs = tmp_path / "rotate.yaml"
    inputs.write_text(yaml.safe_dump({"version": 1, "redis": {"password_file": str(password)}}))
    out = prepare_bundle(
        mode="password-change",
        component="redis",
        inputs=inputs,
        key_file=deployment["key_file"],
        base_bundle=base,
        out_dir=tmp_path / "next",
    )
    gateway = yaml.safe_load((out / "gateway-application.yml").read_text())
    assert gateway["spring"]["data"]["redis"]["password"] == password.read_text()
    assert gateway["spring"]["datasource"]["password"] == "${GATEWAY_DATABASE_PASSWORD}"
    assert (out / "milvus.yaml").read_bytes() == (base / "milvus.yaml").read_bytes()


def test_external_dm_bundle_does_not_require_mysql_native_files(deployment, tmp_path, monkeypatch):
    from bisheng.core.config.credential_tool import check_bundle
    from bisheng.core.config.secret_crypto import get_keyring

    source = yaml.safe_load(deployment["config"].read_text())
    source["database_url"] = "dm+dmPython://BISHENG@dm:5236/?schema=BISHENG"
    deployment["config"].write_text(yaml.safe_dump(source))
    out = prepare_bundle(**deployment)
    monkeypatch.setenv("BS_SECRET_KEYS_FILE", str(deployment["key_file"]))
    get_keyring.cache_clear()
    try:
        settings, _, pending = check_bundle(out, enforce=True)
        assert settings.database_url.startswith("dm+dmPython://")
        assert pending == []
        assert not (out / "mysql.password").exists()
    finally:
        get_keyring.cache_clear()


def test_adoption_materializes_actual_container_environment(deployment, tmp_path):
    data = yaml.safe_load(deployment["config"].read_text())
    data["database_url"] = (
        make_url(data["database_url"])
        .set(password=load_keyring(deployment["key_file"]).encrypt("existing-password").decode())
        .render_as_string(hide_password=False)
    )
    deployment["config"].write_text(yaml.safe_dump(data))
    deployment["config"].write_text(deployment["config"].read_text() + "custom_endpoint: !env ${LEGACY_ENDPOINT}\n")
    snapshot = tmp_path / "runtime.json"
    snapshot.write_text(json.dumps(["LEGACY_ENDPOINT=https://existing.example.invalid/path?a=b"]))
    out = prepare_bundle(
        mode="adopt-key",
        config=deployment["config"],
        key_file=deployment["key_file"],
        out_dir=tmp_path / "adopt",
        runtime_env_file=snapshot,
        environ={},
    )
    assert (
        yaml.safe_load((out / "config.yaml").read_text())["custom_endpoint"]
        == "https://existing.example.invalid/path?a=b"
    )
    assert "!env" not in (out / "config.yaml").read_text()
    assert "!env" in deployment["config"].read_text()


@pytest.mark.parametrize("value", [{"NAME": "secret"}, ["NAME=first", "NAME=second"], ["invalid name=secret"], [42]])
def test_bad_runtime_snapshot_rejected_before_output(deployment, tmp_path, value):
    snapshot = tmp_path / "runtime.json"
    snapshot.write_text(json.dumps(value))
    with pytest.raises(CredentialConfigurationError, match="invalid runtime"):
        prepare_bundle(
            mode="adopt-key",
            config=deployment["config"],
            key_file=deployment["key_file"],
            out_dir=deployment["out_dir"],
            runtime_env_file=snapshot,
        )
    assert not deployment["out_dir"].exists()
