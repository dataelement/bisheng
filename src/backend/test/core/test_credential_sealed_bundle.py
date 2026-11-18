"""All native consumers are authenticated ciphertext, including incremental bundles."""

import json
import secrets

import pytest
import yaml
from cryptography.fernet import Fernet

from bisheng.core.config.credential_artifacts import bundle_native_files
from bisheng.core.config.credential_bundle import prepare_bundle
from bisheng.core.config.secret_crypto import CredentialConfigurationError


@pytest.fixture
def sealed_deployment(tmp_path):
    key = tmp_path / "keys.json"
    key.write_text(json.dumps({"version": 1, "keys": [Fernet.generate_key().decode()]}))
    key.chmod(0o600)
    inputs = {"version": 1}
    passwords = {}
    for name in ["mysql", "redis", "minio", "elasticsearch", "milvus"]:
        value = secrets.token_urlsafe(24)
        passwords[name] = value
        p = tmp_path / name
        p.write_text(value)
        p.chmod(0o600)
        inputs[name] = {"secret_key_file" if name == "minio" else "password_file": str(p)}
    request = tmp_path / "request.yaml"
    request.write_text(yaml.safe_dump(inputs))
    config = tmp_path / "source.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "database_url": "mysql+pymysql://root:legacy@mysql:3306/bisheng",
                "redis_url": "redis://redis:6379/1",
                "celery_redis_url": "redis://redis:6379/2",
                "object_storage": {
                    "type": "minio",
                    "minio": {"endpoint": "minio:9000", "access_key": "minioadmin", "secret_key": "old"},
                },
                "vector_stores": {
                    "milvus": {"connection_args": {"host": "milvus", "port": "19530"}},
                    "elasticsearch": {"url": "http://elasticsearch:9200", "ssl_verify": {}},
                },
            }
        )
    )
    return {"key_file": key, "config": config, "inputs": request, "out_dir": tmp_path / "bundle"}, passwords


def test_native_files_are_plaintext_while_config_stays_ciphertext(sealed_deployment):
    args, passwords = sealed_deployment
    out = prepare_bundle(**args)
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["version"] == 2
    assert manifest["native_storage"] == "plaintext"
    assert (out / "mysql.password").read_text() == passwords["mysql"]
    # Application config must not contain recoverable plaintext passwords.
    config_bytes = (out / "config.yaml").read_bytes()
    assert all(v.encode() not in config_bytes for v in passwords.values())
    native = bundle_native_files(out, args["key_file"])
    assert native["mysql.password"].decode() == passwords["mysql"]
    assert passwords["mysql"] in native["openfga.yaml"].decode()
    assert passwords["minio"] in native["milvus.yaml"].decode()
    assert manifest.get("roles") == []


def test_increment_preserves_other_passwords_without_plaintext_snapshot(sealed_deployment, tmp_path):
    args, values = sealed_deployment
    base = prepare_bundle(**args)
    new = tmp_path / "new-password"
    new.write_text(secrets.token_urlsafe(24))
    request = tmp_path / "change.yaml"
    request.write_text(yaml.safe_dump({"version": 1, "redis": {"password_file": str(new)}}))
    out = prepare_bundle(
        mode="password-change",
        component="redis",
        base_bundle=base,
        key_file=args["key_file"],
        inputs=request,
        out_dir=tmp_path / "changed",
    )
    native = bundle_native_files(out, args["key_file"])
    assert native["mysql.password"].decode() == values["mysql"]
    assert native["redis.password"].decode() == new.read_text()
    assert (
        json.loads((base / "manifest.json").read_text())["deployment_id"]
        == json.loads((out / "manifest.json").read_text())["deployment_id"]
    )
    assert (out / "redis.password").read_text() == new.read_text()
    assert json.loads((out / "manifest.json").read_text())["native_storage"] == "plaintext"


def test_native_payload_tampering_is_not_silently_ignored(sealed_deployment):
    args, _ = sealed_deployment
    out = prepare_bundle(**args)
    p = out / "mysql.password"
    before = p.read_text()
    p.write_text(before + "-tampered")
    # Plaintext native files are readable; check_bundle / consumers must still
    # disagree with encrypted config when passwords diverge.
    native = bundle_native_files(out, args["key_file"])
    assert native["mysql.password"].decode() == before + "-tampered"
    import os

    from bisheng.core.config.credential_tool import check_bundle

    os.environ["BS_SECRET_KEYS_FILE"] = str(args["key_file"])
    with pytest.raises(CredentialConfigurationError):
        check_bundle(out)


def test_template_seeding_is_copy_on_write_and_preserves_rendered_credentials(sealed_deployment, tmp_path):
    import io
    import tarfile

    from bisheng.core.config.credential_artifact_cli import seed_bundle

    args, values = sealed_deployment
    base = prepare_bundle(**args)
    before = {str(p.relative_to(base)): p.read_bytes() for p in base.rglob("*") if p.is_file()}
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w") as tar:
        body = b"log:\n  level: info\n"
        item = tarfile.TarInfo("configs/milvus.yaml")
        item.size = len(body)
        tar.addfile(item, io.BytesIO(body))
    out = tmp_path / "seeded"
    seed_bundle(base, out, args["key_file"], "milvus", io.BytesIO(data.getvalue()))
    native = bundle_native_files(out, args["key_file"])
    assert native["milvus-config/milvus.yaml"] == body
    assert values["milvus"] in native["milvus.yaml"].decode()
    assert before == {str(p.relative_to(base)): p.read_bytes() for p in base.rglob("*") if p.is_file()}
    # Option C: rendered milvus.yaml is host plaintext; application config stays ciphertext.
    assert values["milvus"].encode() not in (out / "config.yaml").read_bytes()
    assert values["milvus"] in (out / "milvus.yaml").read_text()


def test_es_vendor_sample_is_preserved_for_native_setup(sealed_deployment, tmp_path):
    import io
    import tarfile

    from bisheng.core.config.credential_artifact_cli import seed_bundle

    args, _ = sealed_deployment
    base = prepare_bundle(**args)
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as tar:
        content = b"cluster.name: ${cluster_name}\n"
        info = tarfile.TarInfo("config/es_config.sample")
        info.size = len(content)
        tar.addfile(info, io.BytesIO(content))
    out = seed_bundle(base, tmp_path / "seeded-es", args["key_file"], "elasticsearch", io.BytesIO(stream.getvalue()))
    native = bundle_native_files(out, args["key_file"])
    assert native["es-config/es_config.sample"] == content
    assert "es-config/elasticsearch.yml" not in native


def test_published_revision_is_immutable_and_retry_is_idempotent(sealed_deployment, tmp_path):
    from bisheng.core.config.credential_artifact_cli import publish_bundle

    args, values = sealed_deployment
    source = prepare_bundle(**args)
    destination = tmp_path / "published"
    publish_bundle(source, destination, args["key_file"])
    before = {str(p.relative_to(destination)): p.read_bytes() for p in destination.rglob("*") if p.is_file()}
    publish_bundle(source, destination, args["key_file"])
    assert before == {str(p.relative_to(destination)): p.read_bytes() for p in destination.rglob("*") if p.is_file()}
    assert bundle_native_files(destination, args["key_file"])["mysql.password"].decode() == values["mysql"]
    (destination / "config.yaml").write_bytes(b"changed")
    with pytest.raises(CredentialConfigurationError):
        publish_bundle(source, destination, args["key_file"])


def test_plaintext_packages_do_not_require_role_keys(sealed_deployment, tmp_path, monkeypatch):
    from bisheng.core.config.credential_tool import main

    args, _ = sealed_deployment
    bundle = prepare_bundle(**args)
    assert json.loads((bundle / "manifest.json").read_text())["native_storage"] == "plaintext"
    keys = tmp_path / "role-keys"
    keys.mkdir(mode=0o700)
    monkeypatch.setenv("BS_SECRET_KEYS_FILE", str(args["key_file"]))
    # Option C: no derived role keyrings; command is a no-op success.
    assert (
        main(
            [
                "artifact",
                "role-keys",
                "--bundle",
                str(bundle),
                "--key-dir",
                str(keys),
                "--key-file",
                str(args["key_file"]),
            ]
        )
        == 0
    )
    assert list(keys.iterdir()) == []
