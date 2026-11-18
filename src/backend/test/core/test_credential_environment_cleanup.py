"""Environment cleanup distinguishes materialized credentials from live topology."""

import json
from pathlib import Path

import pytest

from bisheng.core.config.credential_artifacts import read_confidential
from bisheng.core.config.credential_bundle import prepare_bundle
from bisheng.core.config.credential_loader import dump_document, load_config, read_env_file
from bisheng.core.config.credential_sealed_migration import sanitize_environment
from bisheng.core.config.secret_crypto import CredentialConfigurationError
from test.core.test_credential_sealed_bundle import sealed_deployment as _sealed_deployment

# Re-export the fixture without shadowing an imported binding in test parameters.
sealed_deployment = _sealed_deployment

ROOT = Path(__file__).resolve().parents[4]
TOPOLOGY = {
    "BS_MILVUS_IS_PARTITION": "false",
    "BS_MILVUS_PARTITION_SUFFIX": "fixture",
    "BS_MINIO_SCHEMA": "false",
    "BS_MINIO_CERT_CHECK": "false",
    "BS_MINIO_ENDPOINT": "minio:9000",
    "BS_MINIO_SHAREPOINT": "https://storage.example.invalid",
}


@pytest.mark.parametrize("shared_password", [False, True])
def test_shipped_topology_survives_but_shared_password_still_blocks(sealed_deployment, tmp_path, shared_password):
    args, values = sealed_deployment
    bundle = prepare_bundle(**args)
    # Read the actual template's reference nodes without evaluating target code.
    template = load_config(
        ROOT / "docker/bisheng/config/config.yaml",
        {
            **TOPOLOGY,
            "BISHENG_GATEWAY_HMAC_SECRET": "",
            "BS_MILVUS_CONNECTION_ARGS": "{}",
            "BS_ELASTICSEARCH_URL": "http://elasticsearch:9200",
            "BS_ELASTICSEARCH_SSL_VERIFY": "{}",
            "BS_MINIO_ACCESS_KEY": "fixture-user",
            "BS_MINIO_SECRET_KEY": "fixture-secret",
        },
    )
    config = bundle / "config.yaml"
    document = load_config(config, {}).data
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["sources"] = {"object_storage.minio.secret_key": "CONSUMED_SECRET"}
    for location, name in template.sources.items():
        if name not in TOPOLOGY:
            continue
        target, source = document, template.raw
        for part in location[:-1]:
            target, source = target[part], source[part]
        target[location[-1]] = source[location[-1]]
        manifest["sources"][".".join(location)] = name
    if shared_password:
        document["customer_field"] = template.raw["object_storage"]["minio"]["secret_key"]
        manifest["sources"]["object_storage.minio.secret_key"] = "BS_MINIO_SECRET_KEY"
    config.write_text(dump_document(document))
    manifest_path.write_text(json.dumps(manifest))
    env = tmp_path / ".env"
    environment = {**TOPOLOGY, "CONSUMED_SECRET": values["minio"], "BS_MINIO_SECRET_KEY": values["minio"]}
    before = "".join(f"{name}={value}\n" for name, value in environment.items())
    env.write_text(before)
    env.chmod(0o600)
    session = tmp_path / "backup"
    if shared_password:
        with pytest.raises(CredentialConfigurationError, match="another config consumer"):
            sanitize_environment(bundle, env, session, key_file=args["key_file"])
        assert env.read_text() == before
        assert not session.exists()
    else:
        sanitize_environment(bundle, env, session, key_file=args["key_file"])
        remaining = read_env_file(env)
        assert {name: remaining[name] for name in TOPOLOGY} == TOPOLOGY
        assert "CONSUMED_SECRET" not in remaining
        assert read_confidential(session / "environment.before.sealed", key_file=args["key_file"]).decode() == before
        assert values["minio"].encode() not in (session / "environment.before.sealed").read_bytes()
        assert (
            load_config(config, remaining).data["object_storage"]["minio"]["endpoint"] == TOPOLOGY["BS_MINIO_ENDPOINT"]
        )
