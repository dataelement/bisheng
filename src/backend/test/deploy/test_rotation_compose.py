"""AC-49, AC-52, AC-55: scoped native recreation preserves existing deployment."""

import copy

import pytest

from bisheng.core.config.secret_crypto import CredentialConfigurationError


@pytest.fixture
def inventory():
    services = {
        "mysql": {
            "image": "private/mysql:8.0",
            "container_name": "old-mysql",
            "environment": {"MYSQL_ROOT_PASSWORD": "old-value", "MYSQL_DATABASE": "custom"},
            "command": ["mysqld", "--skip-name-resolve"],
            "volumes": [{"type": "bind", "source": "/old/mysql/data", "target": "/var/lib/mysql"}],
            "networks": {"default": {}},
        },
        "openfga": {
            "image": "private/fga:pinned",
            "container_name": "old-fga",
            "environment": {"OPENFGA_DATASTORE_URI": "old-dsn", "CUSTOM": "literal$value"},
            "volumes": [],
            "networks": {"default": {}},
        },
        "redis": {
            "image": "private/redis:7",
            "container_name": "old-redis",
            "command": ["redis-server", "/etc/redis.conf", "--requirepass", "old-value", "--maxclients", "900"],
            "volumes": [
                {"type": "bind", "source": "/old/redis", "target": "/data"},
                {"type": "bind", "source": "/old/redis.conf", "target": "/etc/redis.conf"},
            ],
            "networks": {"default": {}},
        },
        "minio": {
            "image": "private/minio:pinned",
            "container_name": "old-minio",
            "environment": {"MINIO_ACCESS_KEY": "same-user", "MINIO_SECRET_KEY": "old-value", "CUSTOM": "keep"},
            "volumes": [{"type": "bind", "source": "/old/objects", "target": "/minio_data"}],
            "networks": {"default": {}},
        },
        "milvus": {
            "image": "private/milvus:2.5.10",
            "container_name": "old-milvus",
            "environment": {"MINIO_ADDRESS": "minio:9000", "CUSTOM": "keep"},
            "mem_limit": "3g",
            "volumes": [{"type": "bind", "source": "/old/vectors", "target": "/var/lib/milvus"}],
            "networks": {"default": {}},
        },
        "elasticsearch": {
            "image": "private/es:8.12.0",
            "container_name": "old-es",
            "environment": {"ELASTICSEARCH_PASSWORD": "old-value", "ELASTICSEARCH_ENABLE_REST_TLS": "true"},
            "volumes": [{"type": "bind", "source": "/old/es", "target": "/bitnami/elasticsearch/data"}],
            "networks": {"default": {}},
        },
    }
    containers = [
        {
            "Name": "/" + s["container_name"],
            "Image": "sha256:" + str(i) * 64,
            "Config": {"Labels": {"com.docker.compose.project": "old-project", "com.docker.compose.service": name}},
            "State": {"Running": True},
        }
        for i, (name, s) in enumerate(services.items(), 1)
    ]
    return {
        "compose": {"services": services, "networks": {"default": {"name": "old-network", "driver": "bridge"}}},
        "containers": containers,
        "project": "old-project",
        "files": {"redis.conf": 'appendonly yes\nrequirepass "old-value"\nmaxmemory-policy noeviction\n'},
    }


def compile_one(inventory, component):
    from bisheng.core.config.credential_rotation_compose import compile_native

    return compile_native(
        inventory,
        component=component,
        bundle="/private/stage",
        installer_root="/new/docker",
        secret_gid="20",
        run_id="a" * 32,
    )


def test_redis_recreate_keeps_original_permissions_mounts_and_other_services(inventory):
    before = copy.deepcopy(inventory)
    result = compile_one(inventory, "redis")
    assert inventory == before
    assert result["services"] == ["redis"]
    service = result["compose"]["services"]["redis"]
    assert service["container_name"] == "old-redis"
    assert "old-value" not in str(service["command"])
    assert service["command"][-2:] == ["--maxclients", "900"]
    assert {x["target"]: x["source"] for x in service["volumes"]}["/data"] == "/old/redis"
    assert result["compose"]["networks"]["default"] == {"external": True, "name": "old-network"}
    assert set(result["compose"]["services"]) == {"redis"}
    assert "minio" not in result["compose"]["services"]
    assert result["redis_conf"] == "appendonly yes\nmaxmemory-policy noeviction\n"


def test_minio_dependency_preserves_milvus_data_resource_and_login_source(inventory):
    result = compile_one(inventory, "minio")
    assert result["services"] == ["minio", "milvus"]
    milvus = result["compose"]["services"]["milvus"]
    assert milvus["mem_limit"] == "3g"
    assert milvus["environment"]["CUSTOM"] == "keep"
    assert {x["target"]: x["source"] for x in milvus["volumes"]}["/var/lib/milvus"] == "/old/vectors"
    env = result["compose"]["services"]["minio"]["environment"]
    assert "MINIO_ACCESS_KEY" not in env and "MINIO_SECRET_KEY" not in env
    assert env["MINIO_ROOT_PASSWORD_FILE"] == "/run/secrets/minio.password"


def test_mysql_consumer_env_cannot_override_new_dsn_and_dollars_are_literal(inventory):
    result = compile_one(inventory, "mysql")
    assert result["services"] == ["mysql", "openfga"]
    fga = result["compose"]["services"]["openfga"]
    assert "OPENFGA_DATASTORE_URI" not in fga["environment"]
    assert fga["environment"]["CUSTOM"] == "literal$$value"
    mysql = result["compose"]["services"]["mysql"]
    assert mysql["command"] == ["mysqld", "--skip-name-resolve"]
    assert mysql["entrypoint"] == ["bash", "/credential-entrypoint.sh"]
    assert "MYSQL_ROOT_PASSWORD" not in mysql["environment"]
    assert "20" in mysql["group_add"]


def test_es_keeps_tls_and_existing_data(inventory):
    result = compile_one(inventory, "elasticsearch")
    assert result["services"] == ["elasticsearch"]
    es = result["compose"]["services"]["elasticsearch"]
    assert es["environment"]["ELASTICSEARCH_ENABLE_REST_TLS"] == "true"
    assert "ELASTICSEARCH_PASSWORD" not in es["environment"]
    assert es["environment"]["ELASTICSEARCH_PASSWORD_FILE"] == "/run/secrets/elasticsearch.password"


def test_foreign_project_or_missing_native_service_rejected(inventory):
    inventory["containers"][0]["Config"]["Labels"]["com.docker.compose.project"] = "another-project"
    with pytest.raises(CredentialConfigurationError):
        compile_one(inventory, "mysql")
    with pytest.raises(CredentialConfigurationError):
        compile_one(inventory, "telemetry_elasticsearch")


def test_redis_include_and_shell_commands_are_not_lossily_rewritten(inventory):
    inventory["files"]["redis.conf"] += "include /unknown/redis.conf\n"
    with pytest.raises(CredentialConfigurationError):
        compile_one(inventory, "redis")
    inventory["files"]["redis.conf"] = "appendonly yes\n"
    inventory["compose"]["services"]["redis"]["command"] = ["sh", "-c", "redis-server /etc/redis.conf"]
    with pytest.raises(CredentialConfigurationError):
        compile_one(inventory, "redis")


def test_runtime_mounts_ports_and_limits_override_stale_source(inventory):
    container = inventory["containers"][0]
    container["Mounts"] = [
        {
            "Type": "bind",
            "Source": "/actual/data",
            "Destination": "/var/lib/mysql",
            "RW": True,
            "Propagation": "rprivate",
        }
    ]
    container["Config"].update(
        {
            "Env": ["MYSQL_ROOT_PASSWORD=old-value"],
            "Cmd": ["mysqld", "--skip-name-resolve"],
            "Entrypoint": ["docker-entrypoint.sh"],
        }
    )
    container["HostConfig"] = {
        "Memory": 1073741824,
        "ReadonlyRootfs": True,
        "CapDrop": ["NET_RAW"],
        "PortBindings": {"3306/tcp": [{"HostIp": "127.0.0.1", "HostPort": "13306"}]},
    }
    container["NetworkSettings"] = {"Networks": {"old-network": {}}}
    result = compile_one(inventory, "mysql")["compose"]["services"]["mysql"]
    assert result["volumes"][0]["source"] == "/actual/data"
    assert result["mem_limit"] == 1073741824
    assert result["read_only"] is True
    assert result["cap_drop"] == ["NET_RAW"]
    assert result["ports"] == [{"target": 3306, "protocol": "tcp", "published": "13306", "host_ip": "127.0.0.1"}]


@pytest.mark.parametrize(
    "command", [["redis-server", "/custom.conf"], ["redis-server", "/etc/redis.conf", "--user", "default", "on"]]
)
def test_unknown_redis_configuration_cannot_be_rewritten(inventory, command):
    inventory["compose"]["services"]["redis"]["command"] = command
    with pytest.raises(CredentialConfigurationError):
        compile_one(inventory, "redis")


def test_option_c_plaintext_manifest_compiles_without_sealed_runtime(inventory, tmp_path):
    """Option C v2 bundles must not require the removed credential-runtime layout."""
    import json

    from bisheng.core.config.credential_rotation_compose import compile_native

    bundle = tmp_path / "stage"
    bundle.mkdir()
    (bundle / "manifest.json").write_text(
        json.dumps(
            {
                "version": 2,
                "revision": "b" * 32,
                "deployment_id": "c" * 32,
                "native_storage": "plaintext",
                "native_files": [],
            }
        )
    )
    for name in ("mysql.password", "mysql-client.cnf", "openfga.yaml", "openfga.env"):
        (bundle / name).write_text("x")
    result = compile_native(
        inventory,
        component="mysql",
        bundle=str(bundle),
        installer_root="/new/docker",
        secret_gid="20",
        run_id="a" * 32,
    )
    assert result["services"] == ["mysql", "openfga"]
    mysql = result["compose"]["services"]["mysql"]
    assert mysql["environment"]["MYSQL_ROOT_PASSWORD_FILE"] == "/run/secrets/mysql.password"
    assert "MYSQL_ROOT_PASSWORD" not in mysql["environment"]
