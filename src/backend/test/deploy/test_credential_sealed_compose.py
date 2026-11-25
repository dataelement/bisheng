"""Option C: native services mount plaintext host files from the credential bundle."""

import copy
from pathlib import Path

import pytest
import yaml

from bisheng.core.config.credential_runtime_compose import apply_runtime
from bisheng.core.config.secret_crypto import CredentialConfigurationError

ROOT = Path(__file__).resolve().parents[4]


@pytest.mark.parametrize(
    "role",
    ["mysql", "mysql-init", "openfga", "openfga-migrate", "redis", "minio", "elasticsearch", "milvus"],
)
def test_runtime_keeps_data_and_mounts_plaintext_bundle_files(role):
    service = {
        "image": "fixture",
        "volumes": ["/keep/data:/data", "/old/mysql.password:/run/secrets/mysql.password:ro"],
        "environment": {"MYSQL_ROOT_PASSWORD": "old-secret", "TZ": "Asia/Shanghai"},
        "ports": ["123:123"],
    }
    original = copy.deepcopy(service)
    result = apply_runtime(
        service,
        role,
        bundle="/new/bundle",
        key_dir="/keys/runtime",
        binary="/tools/runtime",
        deployment="deployment",
        revision="revision",
    )
    assert result["ports"] == original["ports"]
    assert "/keep/data:/data" in result["volumes"]
    assert all("/old/" not in str(v) for v in result["volumes"])
    assert all(".sealed.json" not in str(v) for v in result["volumes"])
    assert all("bisheng-credential-runtime" not in str(v) for v in result["volumes"])
    assert "old-secret" not in str(result)
    assert "/run/bisheng-secrets" not in " ".join(result.get("tmpfs") or [])
    assert service == original


def test_openfga_uses_env_file_for_locked_image_without_config_flag():
    result = apply_runtime(
        {}, "openfga", bundle="/bundle", key_dir="/keys", binary="/runtime", deployment="d", revision="r"
    )
    assert result["command"] == ["run"]
    assert result["entrypoint"] == ["/openfga"]
    assert result["env_file"] == ["/bundle/openfga.env"]
    assert any(str(v).endswith("/etc/openfga/config.yaml:ro") for v in result["volumes"])
    text = (ROOT / "docker/docker-compose.yml").read_text()
    assert "--config=/etc/openfga/config.yaml" not in text
    assert "openfga.env" in text


def test_es_and_milvus_use_plaintext_file_mounts():
    es = apply_runtime(
        {}, "elasticsearch", bundle="/bundle", key_dir="/keys", binary="/runtime", deployment="d", revision="r"
    )
    assert any("/elasticsearch.password:/run/secrets/elasticsearch.password:ro" in str(v) for v in es["volumes"])
    milvus = apply_runtime(
        {}, "milvus", bundle="/bundle", key_dir="/keys", binary="/runtime", deployment="d", revision="r"
    )
    assert any("/milvus.yaml:/milvus/configs/user.yaml:ro" in str(v) for v in milvus["volumes"])


def test_unknown_role_and_native_secret_mount_refused():
    with pytest.raises(CredentialConfigurationError):
        apply_runtime({}, "unknown", bundle="/bundle", key_dir="/keys", binary="/runtime", deployment="d", revision="r")
    with pytest.raises(CredentialConfigurationError):
        apply_runtime(
            {"environment": {"SOME_PASSWORD": "unknown-secret"}},
            "mysql",
            bundle="/bundle",
            key_dir="/keys",
            binary="/runtime",
            deployment="d",
            revision="r",
        )


def test_checked_in_compose_uses_plaintext_native_mounts_without_go_runtime():
    services = yaml.safe_load((ROOT / "docker/docker-compose.yml").read_text())["services"]
    text = (ROOT / "docker/docker-compose.yml").read_text()
    assert "credential-runtime" not in text
    assert ".sealed.json" not in text
    assert "/run/bisheng-secrets" not in text
    for role in ["mysql", "redis", "minio", "elasticsearch", "milvus"]:
        service = services[role]
        assert any(
            "/run/secrets/" in str(v) or "user.yaml:ro" in str(v) or "openfga.yaml" in str(v)
            for v in service.get("volumes", [])
        )
    assert services["backend"].get("entrypoint") != ["/opt/bisheng/credential-runtime", "guard", "--"]
    assert services["backend_worker"].get("entrypoint") != ["/opt/bisheng/credential-runtime", "guard", "--"]
