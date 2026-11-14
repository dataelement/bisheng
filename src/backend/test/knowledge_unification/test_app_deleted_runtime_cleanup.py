"""Deleted APP facts are only readable by its fenced destroy. 覆盖 AC: AC-68, AC-75, AC-87, AC-89, AC-91."""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.app_publish.domain.repositories.reference_source_repository import HostedAppReferenceSourceRepository
from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeAssignment, RuntimeOperation, RuntimeRoute
from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import (
    RuntimeConflict,
    RuntimeDeliveryRepository,
)
from bisheng.app_runtime.domain.services.runtime_operation_service import RuntimeOperationService
from bisheng.app_runtime.domain.services.runtime_protocol import ServiceIdentity
from bisheng.common.errcode.app_factory import AppNotFoundError
from bisheng.database.models.app import App
from test.knowledge_unification import test_app_repository as fixtures

store = fixtures.store
tenant = fixtures.tenant


@pytest.fixture
async def cleanup(store):
    engine, _ = store
    metadata = sa.MetaData()
    table = RuntimeAssignment.__table__
    sa.Table(
        table.name,
        metadata,
        *[
            sa.Column(
                col.name,
                col.type.copy(),
                primary_key=col.primary_key,
                nullable=col.nullable,
                server_default=sa.text("CURRENT_TIMESTAMP")
                if col.name in {"create_time", "update_time"}
                else col.server_default,
            )
            for col in table.columns
        ],
    )
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
    async with AsyncSession(engine) as session, session.begin():
        await session.execute(sa.update(App).where(App.id == "app").values(state="deleted"))
        session.add(
            RuntimeAssignment(
                id="assignment",
                tenant_id=101,
                app_id="app",
                node_id="node",
                generation=3,
                owner_epoch=4,
                active_operation_id="cleanup",
            )
        )
        session.add(
            RuntimeOperation(
                id="cleanup",
                tenant_id=101,
                app_id="app",
                scope_key="101/app",
                idempotency_key="destroy",
                request_digest="0" * 64,
                kind="destroy",
                node_id="node",
                generation=3,
                owner_epoch=4,
                deadline=datetime.utcnow() + timedelta(hours=1),
                status="running",
                cleanup_status="pending",
                payload={"purge_volume": True, "delete_secret_config": True},
            )
        )
        session.add(
            RuntimeRoute(
                id="route",
                tenant_id=101,
                app_id="app",
                route_key="app:app",
                version_id="v1",
                node_id="node",
                exec_ref="previous",
                operation_id="",
                generation=2,
                owner_epoch=4,
                status="stopped",
            )
        )

    @asynccontextmanager
    async def factory():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    return RuntimeOperationService(RuntimeDeliveryRepository(factory)), engine


def identity(node="node"):
    return ServiceIdentity("registered-control-key", node, ("control",))


async def test_fenced_active_destroy_can_read_only_cleanup_facts_and_source_stays_deleted(cleanup):
    service, engine = cleanup
    result = await service.application(identity(), "app")
    assert (result["app_id"], result["tenant_id"], result["node_id"], result["generation"], result["owner_epoch"]) == (
        "app",
        101,
        "node",
        3,
        4,
    )
    assert result["phase"] == "stopped" and result["exec_ref"] == "previous"
    async with AsyncSession(engine) as session, session.begin():
        with pytest.raises(AppNotFoundError):
            await HostedAppReferenceSourceRepository.aget_root(session, "app")


@pytest.mark.parametrize(
    "bad",
    [
        "no_active",
        "wrong_node",
        "wrong_app",
        "wrong_tenant",
        "wrong_generation",
        "wrong_epoch",
        "wrong_scope",
        "stop",
        "deploy",
        "preview",
        "no_purge",
        "no_secret_flag",
        "completed",
        "failed",
        "expired",
        "cleanup_done",
    ],
)
async def test_other_deleted_resource_requests_are_not_cleanup_permission(cleanup, bad):
    service, engine = cleanup
    async with AsyncSession(engine) as session, session.begin():
        changes = {}
        if bad == "no_active":
            await session.execute(sa.update(RuntimeAssignment).values(active_operation_id=""))
        elif bad == "wrong_node":
            changes["node_id"] = "foreign-node"
        elif bad == "wrong_app":
            changes["app_id"] = "foreign"
        elif bad == "wrong_tenant":
            changes["tenant_id"] = 202
        elif bad == "wrong_generation":
            changes["generation"] = 99
        elif bad == "wrong_epoch":
            changes["owner_epoch"] = 99
        elif bad == "wrong_scope":
            changes["scope_key"] = "202/foreign"
        elif bad in {"stop", "deploy", "preview"}:
            changes["kind"] = bad
        elif bad in {"no_purge", "no_secret_flag"}:
            changes["payload"] = {"purge_volume": bad != "no_purge", "delete_secret_config": bad != "no_secret_flag"}
        elif bad in {"completed", "failed"}:
            changes["status"] = bad
        elif bad == "expired":
            changes["deadline"] = datetime.utcnow() - timedelta(seconds=1)
        else:
            changes.update(
                status="timed_out",
                deadline=datetime.utcnow() - timedelta(seconds=1),
                cleanup_status="complete",
                failure={"reason": "operation_timeout"},
            )
        if changes:
            await session.execute(sa.update(RuntimeOperation).where(RuntimeOperation.id == "cleanup").values(**changes))
    with pytest.raises(RuntimeConflict, match="application_not_found"):
        await service.application(identity(), "app")


async def test_existing_exact_timeout_recovery_can_read_cleanup_scope(cleanup):
    service, engine = cleanup
    async with AsyncSession(engine) as session, session.begin():
        await session.execute(
            sa.update(RuntimeOperation)
            .where(RuntimeOperation.id == "cleanup")
            .values(
                status="timed_out",
                cleanup_status="pending",
                deadline=datetime.utcnow() - timedelta(seconds=1),
                failure={"reason": "operation_timeout"},
            )
        )
    assert (await service.application(identity(), "app"))["app_id"] == "app"


async def test_foreign_node_and_unbound_deleted_root_still_refused(cleanup):
    with pytest.raises(RuntimeConflict, match="application_not_found"):
        await cleanup[0].application(identity("foreign-node"), "app")
    with pytest.raises(RuntimeConflict, match="application_not_found"):
        await cleanup[0].application(identity(), "foreign")


async def test_original_live_application_read_is_unchanged(cleanup):
    service, engine = cleanup
    async with AsyncSession(engine) as session, session.begin():
        await session.execute(sa.update(App).where(App.id == "app").values(state="stopped"))
        await session.execute(sa.update(RuntimeOperation).values(kind="deploy", status="completed"))
    assert (await service.application(identity(), "app"))["phase"] == "stopped"
