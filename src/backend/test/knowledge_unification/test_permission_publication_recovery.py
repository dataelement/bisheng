"""Actual original Run SQL/FGA ACK boundaries and stopped-service recovery."""

import asyncio
import json

import pytest
import sqlalchemy as sa

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.knowledge.application.unification_permissions import PermissionPublicationApplication
from bisheng.permission.domain.models import AuthorizationModelRelease, PermissionCatalogRelease, ResourcePermissionMode
from test.knowledge_unification.test_permission_publication_application import (
    app,
)
from test.knowledge_unification.test_permission_publication_application import (
    complete as complete,
)
from test.knowledge_unification.test_permission_publication_application import (
    native as native,
)
from test.knowledge_unification.test_permission_publication_application import (
    published_input as published_input,
)
from test.knowledge_unification.test_permission_publication_application import (
    raw_resource_native as raw_resource_native,
)
from test.knowledge_unification.test_permission_publication_application import (
    resource_native as resource_native,
)
from test.knowledge_unification.test_permission_publication_application import (
    transport as transport,
)


@pytest.mark.parametrize("key", ["permission_catalog", "permission_namespace", "intent", "ack", "permission_complete"])
@pytest.mark.parametrize("after,cancel", [(False, False), (True, False), (True, True)])
async def test_real_sql_commit_unknown_at_each_original_run_boundary_recovers(
    published_input, monkeypatch, key, after, cancel
):
    value = published_input
    original = PermissionPublicationApplication._commit
    fired = False

    async def fault(self, frozen, actual_key, expected, checkpoint, effect=None):
        nonlocal fired
        match = actual_key == key
        if key == "permission_namespace":
            match = match and get_current_tenant_id() == 101
        if key in {"intent", "ack"}:
            cursor = json.loads(checkpoint["cursor"])
            match = actual_key == "permission_fga" and (cursor["pending"] is not None) == (key == "intent")
        if match and not fired:
            fired = True
            value.sessions.fail_at = value.sessions.commits + 1
            value.sessions.after, value.sessions.cancel = after, cancel
        return await original(self, frozen, actual_key, expected, checkpoint, effect)

    monkeypatch.setattr(PermissionPublicationApplication, "_commit", fault)
    with pytest.raises(asyncio.CancelledError if after and cancel else BaseErrorCode):
        await app(value).arun_permissions(**value.input, operator_id=7)
    assert fired
    value.sessions.assert_closed()
    value.sessions.fail_at = None
    assert (await app(value).arun_permissions(**value.input, operator_id=7)).complete
    writes = value.store.writes
    assert (await app(value).arun_permissions(**value.input, operator_id=7)).complete
    assert value.store.writes == writes


@pytest.mark.parametrize("after,cancel", [(False, False), (True, False), (True, True)])
async def test_actual_atomic_pointer_unknown_keeps_sql_old_until_recovery(published_input, after, cancel):
    value = published_input
    fired = False

    async def fault(request):
        nonlocal fired
        if request.url.path.endswith("/write") and not fired:
            body = json.loads(request.content)
            if any(row["relation"] == "active" for row in body.get("writes", {}).get("tuple_keys", ())):
                fired = True
                value.store.fail_write = value.store.writes + 1
                value.store.after, value.store.cancel = after, cancel

    value.store.on_request = fault
    with pytest.raises(asyncio.CancelledError if cancel else BaseErrorCode):
        await app(value).arun_permissions(**value.input, operator_id=7)
    assert fired
    async with value.sessions() as session, session.begin():
        current = (
            await session.execute(
                sa.select(PermissionCatalogRelease).where(PermissionCatalogRelease.status == "CURRENT")
            )
        ).scalar_one()
        assert current.id == value.before.release.id
    value.sessions.assert_closed()
    value.store.fail_write = None
    assert (await app(value).arun_permissions(**value.input, operator_id=7)).complete


@pytest.mark.parametrize("corruption", ["extra", "missing", "mixed"])
async def test_pending_unknown_does_not_adopt_partial_or_extra_store(published_input, corruption):
    value = published_input
    value.store.fail_write, value.store.after = 1, True
    with pytest.raises(BaseErrorCode):
        await app(value).arun_permissions(**value.input, operator_id=7)
    value.store.fail_write = None
    if corruption == "extra":
        value.store.tuples.add(("user:99", "member", "tenant:202"))
    elif corruption == "missing":
        value.store.tuples.remove(("user:42", "member", "tenant:202"))
    else:
        new = next(row for row in value.store.tuples if row[2] == "knowledge_space:9000")
        value.store.tuples.remove(new)
    writes = value.store.writes
    with pytest.raises(BaseErrorCode):
        await app(value).arun_permissions(**value.input, operator_id=7)
    assert value.store.writes == writes


@pytest.mark.parametrize("published_input", [False, True], indirect=True)
async def test_auth_dml_is_selected_once_or_zero_for_same_schema(published_input):
    value = published_input
    # The actual fixture branch is parametrized independently below in a
    # separate same-pin control; every auth UPDATE here must target one row.
    updates = []

    def sql(connection, cursor, statement, parameters, context, many):
        if statement.lstrip().upper().startswith("UPDATE AUTHORIZATION_MODEL_RELEASE"):
            updates.append((statement, parameters))

    sa.event.listen(value.database.engine.sync_engine, "before_cursor_execute", sql)
    try:
        assert (await app(value).arun_permissions(**value.input, operator_id=7)).complete
        count = len(updates)
        assert count == (0 if value.same else 2)
        await app(value).arun_permissions(**value.input, operator_id=7)
        assert len(updates) == count
    finally:
        sa.event.remove(value.database.engine.sync_engine, "before_cursor_execute", sql)


@pytest.mark.parametrize("published_input", [True], indirect=True)
async def test_same_schema_reuses_exact_before_active_and_zero_auth_dml(published_input):
    value = published_input
    updates = []

    def sql(connection, cursor, statement, parameters, context, many):
        if (
            statement.lstrip()
            .upper()
            .startswith(("UPDATE AUTHORIZATION_MODEL_RELEASE", "INSERT INTO AUTHORIZATION_MODEL_RELEASE"))
        ):
            updates.append(statement)

    sa.event.listen(value.database.engine.sync_engine, "before_cursor_execute", sql)
    try:
        await app(value).arun_permissions(**value.input, operator_id=0)
        assert not updates
        assert not any(
            request.method == "POST" and request.url.path.endswith("/authorization-models")
            for request in value.store.requests
        )
        async with value.sessions() as session, session.begin():
            rows = (await session.execute(sa.select(AuthorizationModelRelease))).scalars().all()
            assert len(rows) == 1 and rows[0].status == "ACTIVE" and rows[0].id == value.before.authorization.id
    finally:
        sa.event.remove(value.database.engine.sync_engine, "before_cursor_execute", sql)


async def test_resource_trigger_tail_drift_rolls_back_with_original_run_checkpoint(published_input):
    value = published_input
    async with value.database.engine.begin() as connection:
        await connection.exec_driver_sql(
            "CREATE TRIGGER f118_tail AFTER UPDATE OF resource_type ON resource_permission_mode BEGIN UPDATE permission_grant_assignee SET source_ref='changed' WHERE id=101; END"
        )
    with pytest.raises(BaseErrorCode):
        await app(value).arun_permissions(**value.input, operator_id=7)
    assert value.store.writes == 0
    async with value.sessions() as session, session.begin():
        mode = (
            await session.execute(sa.select(ResourcePermissionMode).where(ResourcePermissionMode.id == 9000))
        ).scalar_one()
        assert mode.resource_type == "knowledge_library"
        row = (
            await session.execute(sa.text("SELECT source_ref FROM permission_grant_assignee WHERE id=101"))
        ).scalar_one()
        assert row == "original-library-source:owner"


@pytest.mark.parametrize("kind", ["model_remote", "auth_sql", "reservation"])
@pytest.mark.parametrize("after,cancel", [(False, False), (True, False), (True, True)])
async def test_real_immutable_prepare_unknown_is_recovered_by_original_model_and_reservation_ports(
    published_input, monkeypatch, kind, after, cancel
):
    value = published_input
    from bisheng.permission.application.catalog_api import SqlCatalogState
    from bisheng.permission.migration.f048_runtime_storage import OpenFGAMigrationModelPublisher

    fired = False

    def fail():
        if cancel:
            raise asyncio.CancelledError()
        raise OSError("preparation acknowledgement unknown")

    if kind == "model_remote":

        async def fault(request):
            nonlocal fired
            if request.method == "POST" and request.url.path.endswith("/authorization-models") and not fired:
                fired = True
                if after:
                    value.store.models["published-target"] = json.loads(request.content)
                fail()

        value.store.on_request = fault
    else:
        owner, name = (
            (OpenFGAMigrationModelPublisher, "_persist_release")
            if kind == "auth_sql"
            else (SqlCatalogState, "reserve_draft")
        )
        original = getattr(owner, name)

        async def fault(self, *args, **kwargs):
            nonlocal fired
            if fired:
                return await original(self, *args, **kwargs)
            fired = True
            if not after:
                fail()
            await original(self, *args, **kwargs)
            fail()

        monkeypatch.setattr(owner, name, fault)
    with pytest.raises(asyncio.CancelledError if cancel else BaseErrorCode):
        await app(value).arun_permissions(**value.input, operator_id=7)
    assert fired and value.store.writes == 0
    value.sessions.assert_closed()
    value.store.on_request = None
    assert (await app(value).arun_permissions(**value.input, operator_id=7)).complete


@pytest.mark.parametrize("already_staged", [False, True])
async def test_empty_expired_reservation_blocks_but_complete_stage_replays(
    published_input, monkeypatch, already_staged
):
    value = published_input
    from datetime import datetime

    from bisheng.permission.application.f118_permission_publish import F118PermissionPublisher
    from bisheng.permission.domain.repositories import f118_catalog_write_repository as writer

    original = F118PermissionPublisher.aprepare

    class Future(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2100, 1, 1, tzinfo=tz)

    if already_staged:
        value.store.fail_write = 1
        with pytest.raises(BaseErrorCode):
            await app(value).arun_permissions(**value.input, operator_id=7)
        value.store.fail_write = None
        monkeypatch.setattr(writer, "datetime", Future)
        assert (await app(value).arun_permissions(**value.input, operator_id=7)).complete
    else:

        async def aged(self, **kwargs):
            result = await original(self, **kwargs)
            monkeypatch.setattr(writer, "datetime", Future)
            return result

        monkeypatch.setattr(F118PermissionPublisher, "aprepare", aged)
        with pytest.raises(BaseErrorCode):
            await app(value).arun_permissions(**value.input, operator_id=7)
        assert value.store.writes == 0
        async with value.sessions() as session, session.begin():
            modes = (await session.execute(sa.select(ResourcePermissionMode))).scalars().all()
            assert all(row.resource_type == "knowledge_library" for row in modes)
