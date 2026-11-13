"""Static deployment contract: file references and prerequisite ordering."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[4]


def services():
    return yaml.safe_load((ROOT / "docker/docker-compose.yml").read_text())["services"]


def test_all_python_consumers_share_external_key_and_bundle():
    for name in ("backend", "backend_worker"):
        service = services()[name]
        assert service["environment"]["BS_SECRET_KEYS_FILE"] == "/run/secrets/bisheng-fernet-keys.json"
        assert not any(
            k in service["environment"]
            for k in ("BS_MINIO_SECRET_KEY", "BS_MILVUS_CONNECTION_ARGS", "BS_ELASTICSEARCH_SSL_VERIFY")
        )
        assert any("/run/secrets/bisheng-fernet-keys.json:ro" in v for v in service["volumes"] if isinstance(v, str))
        assert any("/app/bisheng/config.yaml:ro" in v for v in service["volumes"] if isinstance(v, str))


def test_native_credentials_do_not_appear_in_environment_or_arguments():
    s = services()
    assert "MYSQL_ROOT_PASSWORD" not in s["mysql"]["environment"]
    assert s["mysql"]["environment"]["MYSQL_ROOT_PASSWORD_FILE"] == "/run/secrets/mysql.password"
    assert s["mysql"]["entrypoint"] == ["bash", "/credential-entrypoint.sh"]
    assert s["mysql"]["command"] == ["mysqld"]
    assert any("mysql/credential-entrypoint.sh:/credential-entrypoint.sh:ro" in v for v in s["mysql"]["volumes"])
    assert "OPENFGA_DATASTORE_URI" not in s["openfga"]["environment"]
    assert any("/etc/openfga/config.yaml:ro" in v for v in s["openfga"]["volumes"])
    assert s["minio"]["environment"]["MINIO_ROOT_PASSWORD_FILE"] == "/run/secrets/minio.password"
    assert s["elasticsearch"]["environment"]["ELASTICSEARCH_PASSWORD_FILE"] == "/run/secrets/elasticsearch.password"
    assert "MINIO_SECRET_ACCESS_KEY" not in s["milvus"]["environment"]
    assert any("/milvus/configs/user.yaml:ro" in v for v in s["milvus"]["volumes"])
    assert "--aclfile" in s["redis"]["command"]
    assert "NOAUTH" not in str(s["redis"]["healthcheck"])
    assert "mysql-init" in s["openfga-migrate"]["depends_on"]


def test_health_scripts_are_readonly_and_no_trace_or_password_argv():
    for file in ("mysql/credential-health.sh", "redis/credential-health.sh", "milvus/credential-entrypoint.sh"):
        text = (ROOT / "docker" / file).read_text()
        assert "set -x" not in text and "set -ex" not in text
        assert ' -p"' not in text
    assert "SELECT 1" in (ROOT / "docker/mysql/credential-health.sh").read_text()
    assert "CREATE DATABASE" not in (ROOT / "docker/mysql/credential-health.sh").read_text()
