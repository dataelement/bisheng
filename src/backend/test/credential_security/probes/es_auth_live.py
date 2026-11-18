"""Explicit local ES-only protocol acceptance; never connects to the 166 host."""

import contextlib
import io
import json
import os
import secrets
import subprocess
import time
import traceback
import uuid
from pathlib import Path

import yaml
from cryptography.fernet import Fernet
from elasticsearch import Elasticsearch

from bisheng.core.config import credential_es_migration as es
from bisheng.core.config.credential_artifact_cli import seed_bundle
from bisheng.core.config.credential_artifacts import write_confidential
from bisheng.core.config.credential_sealed_migration import prepare_migration, status, verify_staged
from bisheng.core.config.secret_crypto import get_keyring


def run():
    if os.environ.get("BISHENG_LOCAL_ES_AUTH_ACCEPTANCE") != "yes":
        raise SystemExit("explicit local ES acceptance opt-in required")
    if subprocess.check_output(["docker", "context", "show"]).decode().strip() not in {"colima", "desktop-linux"}:
        raise SystemExit("only an explicit local Docker desktop context is allowed")
    root = Path(__file__).resolve().parents[5] / "docker/.generated" / ("es-auth-live-" + uuid.uuid4().hex)
    root.mkdir(mode=0o700, parents=True)
    project = "credential-es-live-" + uuid.uuid4().hex[:12]
    image = "bitnamilegacy/elasticsearch:8.12.0"
    container = project + "-elasticsearch"
    volume = project + "-data"
    label = "com.bisheng.es-auth-acceptance=" + project
    result = {"status": "running", "project": project, "root": str(root)}
    key = root / "keys.json"
    key.write_text(json.dumps({"version": 1, "keys": [Fernet.generate_key().decode()]}))
    key.chmod(0o600)
    os.environ["BS_SECRET_KEYS_FILE"] = str(key)
    deployment = uuid.uuid4().hex
    os.environ["BS_CREDENTIAL_DEPLOYMENT_ID"] = deployment
    (root / ".artifact-context.json").write_text(
        json.dumps({"version": 2, "revision": uuid.uuid4().hex, "deployment_id": deployment})
    )
    (root / ".artifact-context.json").chmod(0o600)
    get_keyring.cache_clear()
    target_password = secrets.token_urlsafe(24)

    def docker(*args, timeout=180):
        p = subprocess.run(["docker", *args], capture_output=True, timeout=timeout)
        if p.returncode:
            write_confidential(
                root / ("docker-error-" + uuid.uuid4().hex + ".sealed"), p.stdout + p.stderr, key_file=key
            )
            raise RuntimeError("local Docker operation failed; encrypted diagnostics retained")
        return p.stdout

    def wait_port():
        for _ in range(120):
            try:
                with Elasticsearch(endpoint, request_timeout=2, max_retries=0) as c:
                    c.info()
                return
            except Exception:
                time.sleep(1)  # Startup is the only bounded retry; no account writes occur.
        raise RuntimeError("initial local ES startup timeout")

    def compile_up(document):
        file = root / "recreate.json"
        file.write_text(json.dumps(document))
        file.chmod(0o600)
        docker("compose", "-p", project, "-f", str(file), "up", "-d", "--no-deps", "elasticsearch")
        for _ in range(120):
            if docker("exec", container, "cat", "/proc/1/comm").strip() == b"java":
                observed = es.observe_target(session, key)
                if observed != "UNKNOWN":
                    return observed
            time.sleep(1)
        raise RuntimeError("protected ES startup timeout")

    try:
        docker("network", "create", "--label", label, project)
        docker("volume", "create", "--label", label, volume)
        original_compose = {
            "services": {
                "elasticsearch": {
                    "image": image,
                    "container_name": container,
                    "user": "0:0",
                    "mem_limit": "2g",
                    "ulimits": {"core": {"soft": 0, "hard": 0}},
                    "ports": ["127.0.0.1::9200"],
                    "networks": {"default": {"aliases": ["elasticsearch"]}},
                    "volumes": [{"type": "volume", "source": "data", "target": "/bitnami/elasticsearch/data"}],
                    "environment": {
                        "ELASTICSEARCH_ENABLE_SECURITY": "false",
                        "ELASTICSEARCH_ENABLE_REST_TLS": "false",
                        "ELASTICSEARCH_SKIP_TRANSPORT_TLS": "yes",
                        "ELASTICSEARCH_HEAP_SIZE": "512m",
                    },
                }
            },
            "networks": {"default": {"external": True, "name": project}},
            "volumes": {"data": {"external": True, "name": volume}},
        }
        source_compose = root / "source-compose.json"
        source_compose.write_text(json.dumps(original_compose))
        docker("compose", "-p", project, "-f", str(source_compose), "up", "-d", "elasticsearch")
        inspection = json.loads(docker("inspect", container))
        port = inspection[0]["NetworkSettings"]["Ports"]["9200/tcp"][0]["HostPort"]
        endpoint = "http://127.0.0.1:" + port
        wait_port()

        @contextlib.contextmanager
        def local_connection(settings, component):
            # Adapt transport only: all security/index/password APIs hit real ES.
            conf = (
                settings.vector_stores.elasticsearch
                if component == "elasticsearch"
                else settings.telemetry_elasticsearch
            )
            with Elasticsearch(
                endpoint, **conf.ssl_verify, request_timeout=10, max_retries=0, retry_on_timeout=False
            ) as c:
                yield c

        es._es = local_connection
        with Elasticsearch(endpoint, request_timeout=5) as c:
            c.indices.create(index="customer-knowledge")
            c.index(index="customer-knowledge", id="kept", document={"retained": project}, refresh="wait_for")
            c.indices.put_alias(index="customer-knowledge", name="customer-search")
            original = es.index_baseline(c)

        def token():
            return (
                "encrypt("
                + Fernet(json.loads(key.read_text())["keys"][0].encode())
                .encrypt(secrets.token_urlsafe(24).encode())
                .decode()
                + ")"
            )

        db_token = token()[8:-1]
        store = root / "store"
        source = store / "revisions/legacy"
        source.mkdir(mode=0o700, parents=True)
        (store / "migrations").mkdir()
        (store / "deployment.id").write_text(deployment)
        (store / "deployment.id").chmod(0o600)
        config = {
            "database_url": "mysql+pymysql://root:" + db_token + "@mysql:3306/bisheng",
            "redis_url": "redis://:" + token()[8:-1] + "@redis:6379/1",
            "object_storage": {
                "type": "minio",
                "minio": {"endpoint": "minio:9000", "access_key": "minioadmin", "secret_key": token()},
            },
            "vector_stores": {
                "elasticsearch": {"url": "http://elasticsearch:9200", "ssl_verify": {}},
                "milvus": {"connection_args": {"host": "milvus", "port": "19530", "user": "root", "password": token()}},
            },
        }
        config["celery_redis_url"] = config["redis_url"]
        config["telemetry_elasticsearch"] = {"url": "http://elasticsearch:9200", "ssl_verify": {}}
        (source / "config.yaml").write_text(yaml.safe_dump(config))
        (source / "config.yaml").chmod(0o600)
        (source / "manifest.json").write_text(
            json.dumps({"version": 1, "revision": uuid.uuid4().hex, "mode": "adopt-key", "native_files": []})
        )
        (source / "manifest.json").chmod(0o600)
        request = root / "inputs.yaml"
        write_confidential(root / "es.password", target_password, key_file=key)
        request.write_text("version: 1\nelasticsearch:\n  password_file: es.password\n")
        session = prepare_migration(
            source,
            store=store,
            key_file=key,
            out_dir=store / "migrations/test",
            deployment=deployment,
            es_mode="enable",
            inputs=request,
        )
        template = docker("cp", "-L", container + ":/opt/bitnami/elasticsearch/config", "-")
        seeded = seed_bundle(session / "bundle", store / "seeded", key, "elasticsearch", io.BytesIO(template))
        verify_staged(session, seeded, key_file=key)
        es.freeze(session, key)
        before = json.loads(docker("inspect", container))
        compiled = es.compile_es(session, key, io.StringIO(json.dumps(before)), "0")
        observation = compile_up(compiled)
        es.reset_intent(session, key)
        if observation == "DENIED":
            diagnostic = docker(
                "exec",
                "--user",
                "0:0",
                container,
                "bash",
                "-c",
                'set +x; ulimit -c 0; source /opt/bitnami/scripts/libos.sh; IFS= read -r p < /run/secrets/elasticsearch.password || [[ -n $p ]]; printf "%s\\n%s\\n" "$p" "$p" | (exec_as_user elasticsearch /opt/bitnami/elasticsearch/bin/elasticsearch-reset-password --username elastic --interactive --batch)',
            )
            write_confidential(root / "native-reset.sealed", diagnostic, key_file=key)
        es.persist_password(session, key)
        es.verify(session, key)
        docker("restart", container)
        for _ in range(120):
            if es.observe_target(session, key) == "READY":
                break
            time.sleep(1)
        else:
            raise RuntimeError("persisted target credential unavailable after restart")
        es.verify(session, key)
        with Elasticsearch(endpoint, basic_auth=("elastic", target_password)) as c:
            assert c.get(index="customer-knowledge", id="kept")["_source"] == {"retained": project}
            assert es.index_baseline(c) == original
        result.update(enable="passed", restart="passed", original_index="passed", initial_observation=observation)

        es.prepare_rollback(session, key)
        verify_staged(session, status(session, key_file=key)["bundle"], key_file=key)
        assert compile_up(es.export_es(session, key)) == "KEEP"
        es.verify(session, key)
        with Elasticsearch(endpoint) as c:
            assert es.index_baseline(c) == original
        result.update(paired_rollback="passed", status="passed")
    except Exception as error:
        result.update(status="failed", error_type=type(error).__name__)
        write_confidential(root / ("failure-" + uuid.uuid4().hex + ".sealed"), traceback.format_exc(), key_file=key)
    finally:
        # Exact project ownership, never host-wide prune or volume cleanup.
        ids = (
            subprocess.check_output(["docker", "ps", "-aq", "--filter", "label=com.docker.compose.project=" + project])
            .decode()
            .split()
        )
        for cid in ids:
            subprocess.run(["docker", "rm", "-f", "-v", cid], capture_output=True)
        subprocess.run(["docker", "network", "rm", project], capture_output=True)
        subprocess.run(["docker", "volume", "rm", volume], capture_output=True)
        result["cleanup_complete"] = (
            not subprocess.check_output(
                ["docker", "ps", "-aq", "--filter", "label=com.docker.compose.project=" + project]
            ).strip()
            and subprocess.run(["docker", "network", "inspect", project], capture_output=True).returncode != 0
            and subprocess.run(["docker", "volume", "inspect", volume], capture_output=True).returncode != 0
        )
        (root / "result.json").write_text(json.dumps(result, indent=2))
        print(json.dumps(result))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(run())
