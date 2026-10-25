"""Actual route-bound snapshots. 覆盖 AC: AC-68, AC-80, AC-90."""

from datetime import datetime, timedelta

import pytest

from test.app_runtime.test_runtime_delivery_repository import runtime_repo as runtime_repo


@pytest.fixture
async def secret_runtime(runtime_repo, monkeypatch):
    from cryptography.fernet import Fernet

    from bisheng.app_publish.domain.models.app_secret_config import AppSecretConfig
    from bisheng.app_publish.domain.models.hosted_app_subject import HostedAppSubject
    from bisheng.app_runtime.domain.models.runtime_delivery import (
        RuntimeAssignment,
        RuntimeDelivery,
        RuntimeOperation,
        RuntimeRoute,
    )
    from bisheng.app_runtime.domain.services.runtime_payload import seal
    from bisheng.common.services.config_service import settings
    from bisheng.database.models.app import App
    from bisheng.database.models.app_instance import AppInstance
    from bisheng.database.models.app_version import AppVersion
    from bisheng.database.models.audit_log import AuditLog
    from bisheng.open_api.domain.models.api_credential import ApiCredential
    from bisheng.open_api.domain.models.credential_delegate_scope import ApiCredentialDelegateScope
    from test.app_publish.conftest import _sqlite_ddl_quirks

    models = [
        App,
        AppVersion,
        AppInstance,
        AppSecretConfig,
        HostedAppSubject,
        ApiCredential,
        ApiCredentialDelegateScope,
        AuditLog,
    ]
    async with runtime_repo._factory() as session:
        engine = session.bind
    with _sqlite_ddl_quirks([model.__table__ for model in models]):
        async with engine.begin() as connection:
            for model in models:
                await connection.run_sync(lambda conn, model=model: model.__table__.create(conn, checkfirst=True))
    monkeypatch.setattr(settings.app_runtime, "runtime_payload_key", Fernet.generate_key().decode())
    monkeypatch.setattr(settings.app_runtime, "runtime_platform_base_url", "http://platform:7860")
    app = App(
        id="app-a",
        slug="secret-app",
        name="Secret app",
        owner_user_id=7,
        tenant_id=1,
        state="online",
        current_version_id="v1",
        pending_version_id="pending-v2",
    )
    version = AppVersion(
        id="v1",
        app_id=app.id,
        version_no=1,
        kind="initial",
        terminal_state="online",
        code_object_key="code.tar.gz",
        manifest={"runtime": "python3.11", "port": 8080},
        capabilities={"secrets": [{"name": "API_KEY"}]},
        injections={},
        tier_id="light",
        runtime="python3.11",
        image_ref="image@sha256:" + "a" * 64,
    )
    delivery = {"mode": "image", "image_ref": version.image_ref}
    op = RuntimeOperation(
        id="origin",
        tenant_id=1,
        app_id=app.id,
        scope_key="1/app-a",
        idempotency_key="origin",
        request_digest="a" * 64,
        kind="deploy",
        node_id="node-a",
        version_id=version.id,
        status="completed",
        stage="serving",
        cleanup_status="complete",
        deadline=datetime.utcnow() + timedelta(hours=1),
        payload={
            "tier": {"memory_mb": 128, "cpu_millicores": 100},
            "resolved_delivery": delivery,
            "sealed_env": seal({"API_KEY": "old-value"}),
        },
    )
    async with runtime_repo.transaction() as session:
        for row in [
            app,
            version,
            op,
            RuntimeDelivery(
                tenant_id=1,
                app_id=app.id,
                version_id=version.id,
                execution_mode="image",
                delivery_digest="a" * 64,
                content=delivery,
            ),
            RuntimeAssignment(tenant_id=1, app_id=app.id, node_id="node-a", active_operation_id=op.id, generation=1),
            RuntimeRoute(
                id="route-a",
                tenant_id=1,
                app_id=app.id,
                operation_id=op.id,
                route_key="app:app-a",
                version_id=version.id,
                node_id="node-a",
                exec_ref="old-instance",
                generation=1,
                owner_epoch=1,
                route_epoch=3,
                status="serving",
                target={"host": "172.20.0.2", "port": 8080},
            ),
            AppInstance(app_id=app.id, tenant_id=1, version_id=version.id, phase="running", exec_ref="old-instance"),
        ]:
            session.add(row)
    return runtime_repo, app, version


async def test_snapshot_requires_current_route_instance_and_operation(secret_runtime):
    from bisheng.app_runtime.application.runtime_secrets import running_environment_snapshot
    from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeRoute

    repo, app, _ = secret_runtime
    async with repo.transaction() as session:
        snapshot = await running_environment_snapshot(app.id, session=session)
        assert snapshot.env == {"API_KEY": "old-value"}
        assert snapshot.route_epoch == 3 and snapshot.version_id == "v1"
        assert "old-value" not in repr(snapshot)
    route = (await repo.find(RuntimeRoute, app_id=app.id))[0]
    route.exec_ref = "wrong-instance"
    await repo.save(route)
    async with repo.transaction() as session:
        assert await running_environment_snapshot(app.id, session=session) is None
