"""Operational entry uses actual frozen artifacts and original M3→M4 execution."""

import importlib
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
import sqlalchemy as sa

from bisheng.knowledge.domain.models.knowledge_unification_run import KnowledgeUnificationRun as Run
from test.knowledge_unification.test_migration_references_application import (
    complete as complete,
)
from test.knowledge_unification.test_migration_references_application import (
    native as native,
)
from test.knowledge_unification.test_migration_references_application import (
    no_real_network as no_real_network,
)
from test.knowledge_unification.test_migration_references_application import (
    published_input as published_input,
)
from test.knowledge_unification.test_migration_references_application import (
    raw_resource_native as raw_resource_native,
)
from test.knowledge_unification.test_migration_references_application import (
    resource_native as resource_native,
)
from test.knowledge_unification.test_migration_references_application import (
    transport as transport,
)


def entry():
    return importlib.import_module("scripts.unify_knowledge_spaces")


def arguments(value, *extra):
    return (
        entry()
        .parser()
        .parse_args(
            [
                "--run-id",
                value.input["run_id"],
                "--environment",
                value.input["environment"],
                "--backup-ref",
                json.dumps(value.input["backup_ref"]),
                "--schema-ref",
                json.dumps(value.input["schema_ref"]),
                *extra,
            ]
        )
    )


def runtime(value):
    @asynccontextmanager
    async def open_runtime(*args, **kwargs):
        yield SimpleNamespace(store=value.artifacts.store, sessions=value.sessions, inventory=None)

    return open_runtime


async def test_default_preview_is_read_only_and_reports_actual_frozen_scope(published_input):
    value, writes = published_input, []

    def observe(connection, cursor, statement, parameters, context, many):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            writes.append(statement)

    sa.event.listen(value.database.engine.sync_engine, "before_cursor_execute", observe)
    try:
        result = await entry().arun(arguments(value), runtime_factory=runtime(value))
    finally:
        sa.event.remove(value.database.engine.sync_engine, "before_cursor_execute", observe)
    assert result["mode"] == "preview" and result["tenant_ids"] == list(value.frozen.tenant_ids)
    assert result["ready"] is False and not writes and value.store.writes == 0
    value.sessions.assert_closed()


async def test_apply_and_same_run_resume_reach_real_certificate(published_input):
    value = published_input
    args = arguments(value, "--apply", "--operator-id", "7")
    result = await entry().arun(args, runtime_factory=runtime(value))
    assert result["ready"] is True and result["coverage_epoch"] > 0
    assert result["invalid_manifest_ref"] == value.frozen.plan_ref
    args.resume = True
    assert await entry().arun(args, runtime_factory=runtime(value)) == result
    async with value.sessions() as session, session.begin():
        assert (
            await session.execute(sa.select(Run.phase).where(Run.run_id == value.frozen.run_id))
        ).scalar_one() == "completed"


def test_cli_requires_explicit_apply_and_valid_operator():
    module = entry()
    args = module.parser().parse_args(
        [
            "--run-id",
            "native",
            "--environment",
            "test",
            "--backup-ref",
            json.dumps({"object_key": "native/material", "sha256": "a" * 64}),
            "--schema-ref",
            json.dumps({"object_key": "native/material", "sha256": "a" * 64}),
        ]
    )
    assert not args.apply and not args.resume
    with pytest.raises(SystemExit):
        module.parser().parse_args(
            [
                "--run-id",
                "native",
                "--environment",
                "test",
                "--backup-ref",
                json.dumps({"object_key": "native/material", "sha256": "a" * 64}),
                "--schema-ref",
                json.dumps({"object_key": "native/material", "sha256": "a" * 64}),
                "--apply",
                "--operator-id",
                "-1",
            ]
        )


async def test_apply_without_run_calls_actual_native_m2_before_original_chain(published_input):
    from test.knowledge_unification import test_migration_inventory_application as m2

    value = published_input
    # Start from the actual pre-conversion SQL state, with no frozen Run.
    # Immutable fixture objects remain harmless content-addressed evidence.
    async with value.sessions() as session, session.begin():
        await session.execute(sa.delete(Run.__table__))
    value.store.enforce_closed = False  # M2's original read TX intentionally spans its read-only evidence IO.

    @asynccontextmanager
    async def native_runtime(args):
        @asynccontextmanager
        async def inventory(session):
            yield m2.application(
                importlib.import_module("bisheng.knowledge.application.unification_inventory"), value.artifacts
            )

        yield SimpleNamespace(store=value.artifacts.store, sessions=value.sessions, inventory=inventory)

    result = await entry().arun(arguments(value, "--apply", "--operator-id", "7"), runtime_factory=native_runtime)
    assert result["ready"] is True and result["complete"] is True
