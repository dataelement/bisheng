"""Prepare a fresh local-only platform from the release Compose contract.

Requires the repository's existing PyYAML/cryptography development environment.
Writes random secrets and state only to a NEW external runtime directory.
No Docker operation, D access, model credential discovery or deployment occurs.
"""

from __future__ import annotations

import argparse
import ast
from copy import deepcopy
from pathlib import Path
import re
import secrets

from cryptography.fernet import Fernet
import yaml

REPO = Path(__file__).resolve().parents[3]
SERVICES = (
    "mysql",
    "openfga-migrate",
    "openfga",
    "redis",
    "backend",
    "backend_worker",
    "frontend",
    "elasticsearch",
    "etcd",
    "minio",
    "milvus",
    "code-runner-1",
    "code-runner-2",
)


def prepare(destination: Path, business: Path, openfga_image: str, minio_image: str):
    if destination == REPO or REPO in destination.parents:
        raise ValueError(
            "Private platform runtime must be outside the source repository"
        )
    destination.mkdir(mode=0o700)  # Refuse to overwrite an existing environment.
    data = destination / "data"
    data.mkdir(mode=0o700)
    for name in (
        "mysql",
        "redis",
        "bisheng",
        "es",
        "etcd",
        "minio",
        "milvus",
        "runner-1",
        "runner-2",
    ):
        (data / name).mkdir(mode=0o700)
    password = secrets.token_hex(24)
    minio_key, minio_secret, sandbox_token = (secrets.token_hex(24) for _ in range(3))
    values = dict(
        line.split("=", 1)
        for line in (REPO / "docker/.env.example").read_text().splitlines()
        if line and not line.startswith("#") and "=" in line
    )
    values.update(
        BISHENG_BACKEND_IMAGE="zhgyl302/backend:local",
        BISHENG_FRONTEND_IMAGE="nginx:1.28-alpine",
        BISHENG_SANDBOX_IMAGE="cr.dataelem.com/dataelement/bisheng-sandbox:v3.0.2-arm64",
        MYSQL_IMAGE="mysql:8.0",
        REDIS_IMAGE="redis:7.0.4",
        ELASTICSEARCH_IMAGE="docker.elastic.co/elasticsearch/elasticsearch:8.12.0",
        ETCD_IMAGE="quay.io/coreos/etcd:v3.5.5",
        MILVUS_IMAGE="milvusdb/milvus:v2.5.10",
        MINIO_ROOT_USER=minio_key,
        MINIO_ROOT_PASSWORD=minio_secret,
        SANDBOX_TOKEN=sandbox_token,
        BISHENG_NETWORK_NAME="zhgyl302_isolated",
        COMPOSE_PROJECT_NAME="zhgyl302-platform",
    )
    # These two release images are explicit to make architecture choices reviewable.
    values.update(OPENFGA_IMAGE=openfga_image, MINIO_IMAGE=minio_image)
    (destination / "platform.env").write_text(
        "".join(f"{key}={value}\n" for key, value in values.items())
    )
    (destination / "platform.env").chmod(0o600)
    original = yaml.safe_load((REPO / "docker/docker-compose.yml").read_text())
    services = {name: deepcopy(original["services"][name]) for name in SERVICES}
    port_map = {
        "frontend": ["127.0.0.1:13001:3001"],
        "backend": ["127.0.0.1:17860:7860"],
    }
    for name, service in services.items():
        service.pop("container_name", None)
        service.pop("profiles", None)
        service["restart"] = "no"
        service["ports"] = port_map.get(name, [])
        service["networks"] = (
            ["isolated", "executor"]
            if name in ("backend", "backend_worker")
            else ["executor"]
            if name.startswith("code-runner")
            else ["isolated"]
        )
    services["mysql"]["environment"]["MYSQL_ROOT_PASSWORD"] = password
    services["mysql"]["volumes"] = [
        f"{REPO}/docker/mysql/conf/my.cnf:/etc/mysql/my.cnf:ro",
        f"{data}/mysql:/var/lib/mysql",
    ]
    for name in ("openfga", "openfga-migrate"):
        services[name]["environment"]["OPENFGA_DATASTORE_URI"] = (
            f"root:{password}@tcp(mysql:3306)/openfga?parseTime=true"
        )
    services["redis"]["volumes"] = [f"{data}/redis:/data"]
    services["redis"]["command"] = ["redis-server", "--appendonly", "yes"]
    # Official ARM image runs as elasticsearch. The daemon-local volume keeps
    # its native ownership and also stays on this task's SSD virtual disk.
    services["elasticsearch"].pop("user", None)
    services["elasticsearch"]["volumes"] = ["es-data:/usr/share/elasticsearch/data"]
    services["elasticsearch"]["environment"].update(
        {
            "discovery.type": "single-node",
            "xpack.security.enabled": "false",
            "ES_JAVA_OPTS": "-Xms512m -Xmx512m",
        }
    )
    services["etcd"]["volumes"] = [f"{data}/etcd:/etcd"]
    services["minio"]["volumes"] = [f"{data}/minio:/minio_data"]
    # The release registry has this exact MinIO version only for amd64.
    # The isolated VM's registered qemu-x86_64 handler runs it explicitly.
    services["minio"]["platform"] = "linux/amd64"
    services["milvus"]["volumes"] = [f"{data}/milvus:/var/lib/milvus"]
    for index in (1, 2):
        services[f"code-runner-{index}"]["volumes"] = [
            f"{data}/runner-{index}:/sessions"
        ]
        services[f"code-runner-{index}"]["environment"]["SANDBOX_MAX_SESSIONS"] = "5"
    settings_source = (REPO / "src/backend/bisheng/core/config/settings.py").read_text()
    key = ast.literal_eval(
        re.search(r"^secret_key = (.+)$", settings_source, re.M).group(1)
    )
    encrypted = Fernet(key).encrypt(password.encode()).decode()
    config = (REPO / "docker/bisheng/config/config.yaml").read_text()
    config = re.sub(
        r"mysql\+pymysql://root:[^@]+@mysql",
        f"mysql+pymysql://root:{encrypted}@mysql",
        config,
    )
    (destination / "config.yaml").write_text(config)
    (destination / "config.yaml").chmod(0o600)
    for name in ("backend", "backend_worker"):
        service = services[name]
        service["environment"]["PROCUREMENT_API_ORIGIN"] = (
            "http://procurement-api:18768"
        )
        service["volumes"] = [
            f"{destination}/config.yaml:/app/bisheng/config.yaml:ro",
            f"{data}/bisheng:/app/data",
            f"{business}/private/procurement:/app/data/procurement-private",
            f"{business}/private/transport:/app/transport-private:ro",
            f"{business}/private/customs:/app/customs-private:ro",
            f"{REPO}/integrations/zhgyl/services/transport-history:/app/transport-runtime:ro",
            f"{REPO}/integrations/zhgyl/services/customs-history:/app/customs-runtime:ro",
        ]
    services["backend"]["build"] = {
        "context": str(REPO / "src/backend"),
        "dockerfile": str(
            REPO / "integrations/zhgyl/platform/backend-overlay.Dockerfile"
        ),
    }
    services["backend_worker"]["depends_on"]["backend"] = {
        "condition": "service_healthy"
    }
    # src/backend/entrypoint.sh's worker mode runs Celery + Beat only.
    # Keep the task consumer explicit so a healthy Celery worker cannot hide
    # a missing Linsight worker while Skill runs remain queued.
    services["backend_linsight"] = deepcopy(services["backend_worker"])
    services["backend_linsight"]["command"] = "sh entrypoint.sh linsight"
    nginx = (REPO / "docker/nginx/conf.d/default.conf").read_text()
    orders_location = (business / "orders-nginx.conf").read_text()
    locations = (
        (REPO / "integrations/zhgyl/forecast/bisheng-nginx.conf").read_text()
        + "\n"
        + orders_location
        + orders_location.replace(
            "location = /api/zhgyl/orders", "location = /workspace/api/zhgyl/orders"
        )
    )
    nginx = nginx[: nginx.rfind("}")] + locations + "\n}\n"
    (destination / "frontend.conf").write_text(nginx)
    (destination / "frontend.conf").chmod(0o600)
    services["frontend"]["volumes"] = [
        f"{REPO}/docker/nginx/nginx.conf:/etc/nginx/nginx.conf:ro",
        f"{destination}/frontend.conf:/etc/nginx/conf.d/default.conf:ro",
        f"{REPO}/src/frontend/client/build:/usr/share/nginx/html/client:ro",
        f"{REPO}/src/frontend/platform/build:/usr/share/nginx/html/platform:ro",
    ]
    compose = {
        "name": "zhgyl302-platform",
        "services": services,
        "networks": {
            "isolated": {"external": True, "name": "zhgyl302_isolated"},
            "executor": {"name": "zhgyl302_executor", "internal": True},
        },
        "volumes": {"es-data": {"name": "zhgyl302_es"}},
    }
    (destination / "compose.yaml").write_text(
        yaml.safe_dump(compose, allow_unicode=True, sort_keys=False)
    )
    (destination / "compose.yaml").chmod(0o600)
    print("Prepared external private platform runtime:", destination)


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--destination", type=Path, required=True)
parser.add_argument("--business-runtime", type=Path, required=True)
parser.add_argument("--openfga-image", required=True)
parser.add_argument("--minio-image", required=True)
if __name__ == "__main__":
    options = parser.parse_args()
    prepare(
        options.destination.resolve(),
        options.business_runtime.resolve(),
        options.openfga_image,
        options.minio_image,
    )
