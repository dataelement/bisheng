"""Opt-in loopback fixture with disposable local Docker stores, never application config."""

import argparse
import asyncio
import io
import json
import secrets
import subprocess
import time
from contextlib import contextmanager


@contextmanager
def docker_stores():
    docker = "/usr/local/bin/docker"
    endpoint = subprocess.check_output(
        [docker, "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"], text=True
    ).strip()
    if not endpoint.startswith("unix://"):
        raise RuntimeError("Only a local Unix Docker engine is permitted")
    owned = []
    suffix = secrets.token_hex(6)

    def start(role, image, port, env, *args):
        name = f"e2e-dsh-audit-{role}-{suffix}"
        command = [docker, "run", "-d", "--name", name, "--label", "bisheng.test=dsh-audit", "-p", f"127.0.0.1::{port}"]
        for key, value in env.items():
            command.extend(["-e", f"{key}={value}"])
        subprocess.check_output([*command, image, *args], stderr=subprocess.DEVNULL)
        owned.append(name)
        output = subprocess.check_output([docker, "port", name, str(port)], text=True).strip()
        return int(output.split(":")[-1])

    try:
        mysql_password = secrets.token_hex(24)
        mysql_port = start(
            "mysql", "mysql:8.0", 3306, {"MYSQL_ROOT_PASSWORD": mysql_password, "MYSQL_DATABASE": "dsh_audit"}
        )
        redis_port = start("redis", "redis:7.2", 6379, {}, "redis-server", "--save", "", "--appendonly", "no")
        minio_user, minio_password = secrets.token_hex(12), secrets.token_hex(24)
        minio_port = start(
            "minio",
            "minio/minio:RELEASE.2025-04-22T22-12-26Z",
            9000,
            {"MINIO_ROOT_USER": minio_user, "MINIO_ROOT_PASSWORD": minio_password},
            "server",
            "/data",
        )
        from sqlalchemy import create_engine, text

        engine = create_engine(
            f"mysql+pymysql://root:{mysql_password}@127.0.0.1:{mysql_port}/dsh_audit",
            hide_parameters=True,
            pool_pre_ping=True,
        )
        from minio import Minio

        client = Minio(f"127.0.0.1:{minio_port}", access_key=minio_user, secret_key=minio_password, secure=False)
        for attempt in range(120):
            try:
                with engine.connect() as connection:
                    connection.execute(text("SELECT 1"))
                if not client.bucket_exists("e2e-dsh-audit"):
                    client.make_bucket("e2e-dsh-audit")
                break
            except Exception:
                if attempt == 119:
                    raise RuntimeError("Isolated Docker stores did not become ready") from None
                time.sleep(0.25)
        from redis.asyncio import Redis

        redis = Redis(host="127.0.0.1", port=redis_port, decode_responses=True, socket_timeout=1)

        class MinioStorage:
            bucket = "e2e-dsh-audit"
            minio_client_sync = client

            async def put_object(self, *, object_name, file, content_type):
                await asyncio.to_thread(
                    client.put_object, self.bucket, object_name, io.BytesIO(file), len(file), content_type=content_type
                )

        from bisheng.core.storage.minio import minio_manager

        original = minio_manager.get_minio_storage

        async def isolated_storage():
            return MinioStorage()

        minio_manager.get_minio_storage = isolated_storage
        try:
            yield (
                engine,
                redis,
                {"mysql_port": mysql_port, "redis_port": redis_port, "minio_port": minio_port, "containers": owned},
            )
        finally:
            minio_manager.get_minio_storage = original
            engine.dispose()
    finally:
        for name in owned:
            subprocess.run([docker, "rm", "-f", "-v", name], check=True, stdout=subprocess.DEVNULL)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8786)
    parser.add_argument("--real-stores", action="store_true", required=True)
    args = parser.parse_args()
    from test.fixtures.mock_services import premock_import_chain

    premock_import_chain()
    import uvicorn
    from sqlmodel import SQLModel

    from bisheng.core.database import tenant_filter
    from bisheng.dsh.domain.schemas.model_audit import AuditModeCommand
    from bisheng.dsh.infrastructure.model_audit_activity import RedisAuditActivity
    from bisheng.dsh.infrastructure.model_audit_keys import AuditKeyRing
    from bisheng.dsh.infrastructure.model_audit_storage import BishengMinioAuditObjects, EncryptedAuditStorage
    from test.dsh.model_audit_fixtures import AUDIT_MODELS
    from test.dsh.model_audit_harness import AuditHarness

    tokens = {secrets.token_hex(24): user for user in (1, 2, 20, 21, 30)}
    with docker_stores() as (engine, redis, stores):
        SQLModel.metadata.create_all(engine, tables=[model.__table__ for model in AUDIT_MODELS])
        tenant_filter.register_tenant_filter_events()
        tenant_filter._tenant_aware_tables.update(model.__tablename__ for model in AUDIT_MODELS)
        storage = EncryptedAuditStorage(
            BishengMinioAuditObjects(),
            AuditKeyRing({"fixture": secrets.token_bytes(32)}, active_id="fixture"),
            max_block_bytes=16384,
        )
        activity = RedisAuditActivity(redis, interval=1, maximum=4096, observation_window=300)
        harness = AuditHarness(engine, storage, tokens=tokens, activity=activity)

        async def run():
            await harness.modes.change_admin(
                1, 2, AuditModeCommand(operation_id=secrets.token_hex(16), expected_version=0, mode="CONTENT")
            )
            print(json.dumps({"base": f"http://127.0.0.1:{args.port}", "tokens": tokens, **stores}), flush=True)
            server = uvicorn.Server(
                uvicorn.Config(harness.app, host="127.0.0.1", port=args.port, access_log=False, log_level="warning")
            )
            try:
                await server.serve()
            finally:
                await harness.close()
                await redis.aclose()

        try:
            asyncio.run(run())
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
