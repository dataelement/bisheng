"""Native candidate consumption and closed semantic directory validation."""

from dataclasses import replace
from datetime import datetime

import pytest
import sqlalchemy as sa

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.knowledge.application.unification_reference_reconciliation import (
    DIRECTORY,
    SEMANTICS,
    collect_semantics,
    inspect_reference_reconciliation,
    load_semantics,
)
from bisheng.knowledge.domain.repositories.unification_inventory_repository import ChannelRow
from bisheng.knowledge.domain.services.unification_fingerprints import canonical
from bisheng.resource_reference.application.contracts import SourceKey
from test.knowledge_unification.test_migration_registration import (
    complete as complete,
)
from test.knowledge_unification.test_migration_registration import (
    native as native,
)
from test.knowledge_unification.test_migration_registration import (
    no_real_network as no_real_network,
)
from test.knowledge_unification.test_migration_registration import (
    prepared,
    run_registration,
)
from test.knowledge_unification.test_migration_registration import (
    published_input as published_input,
)
from test.knowledge_unification.test_migration_registration import (
    raw_resource_native as raw_resource_native,
)
from test.knowledge_unification.test_migration_registration import (
    resource_native as resource_native,
)
from test.knowledge_unification.test_migration_registration import (
    transport as transport,
)
from test.knowledge_unification.test_permission_publication_application import app


async def put(value, manifest):
    return await value.artifacts.store.aput_canonical(
        run_id=value.frozen.run_id,
        kind="verification",
        content=canonical(
            {
                "schema_version": 1,
                "run_id": value.frozen.run_id,
                "kind": "verification",
                "records": [manifest],
            }
        ),
    )


async def test_native_current_budget_metadata_does_not_change_the_verification_manifest(published_input, monkeypatch):
    from bisheng.knowledge.application import unification_reference_reconciliation as reconciliation
    from test.knowledge_unification.test_migration_registration import (
        test_added_zero_reference_workflow_requires_real_registration as seed_registered,
    )

    value = published_input
    await seed_registered(value, True)
    application = app(value)
    before = await inspect_reference_reconciliation(
        application, frozen=value.frozen, environment=value.input["environment"], operator_id=7
    )
    original = reconciliation.verify_proven_native_current

    async def different_budget(*args, **kwargs):
        facts = await original(*args, **kwargs)
        return {**facts, "source_bytes": facts["source_bytes"] + 1024}

    monkeypatch.setattr(reconciliation, "verify_proven_native_current", different_budget)
    after = await inspect_reference_reconciliation(
        application, frozen=value.frozen, environment=value.input["environment"], operator_id=7
    )
    assert not before["diagnostics"] and after == before


async def test_semantic_projection_excludes_only_the_explicit_operational_clock():
    key = SourceKey(101, "channel_sync", "channel", "current")

    class Source:
        root = ChannelRow("channel", 101, 7, False, datetime(2026, 11, 20, 1))

        async def aload_reference_source(self, *args, **kwargs):
            return self.root, None, ()

    source = Source()
    with tenant_execution_scope(101):
        first = await collect_semantics(object(), source_keys=(key,), repository=source)
        source.root = replace(source.root, update_time=datetime(2026, 11, 20, 2))
        clock = await collect_semantics(object(), source_keys=(key,), repository=source)
        assert first["sources"][0]["semantic_digest"] == clock["sources"][0]["semantic_digest"]
        assert first["sources"][0]["business_digest"] != clock["sources"][0]["business_digest"]
        source.root = replace(source.root, user_id=8)
        owner = await collect_semantics(object(), source_keys=(key,), repository=source)
        assert owner["sources"][0]["semantic_digest"] != clock["sources"][0]["semantic_digest"]


@pytest.mark.parametrize("damage", [None, "count", "scope", "duplicate", "missing_leaf", "boolean_schema"])
async def test_semantic_directory_hash_scope_count_and_full_dag(published_input, damage):
    value = published_input
    row = {
        "key": {"tenant_id": 101, "source_type": "channel_sync", "source_id": "first", "source_version": "current"},
        "semantic_digest": "a" * 64,
        "business_digest": "b" * 64,
    }
    leaf = await put(
        value,
        {
            "schema_version": True if damage == "boolean_schema" else 1,
            "semantic_contract": SEMANTICS,
            "tenant_id": 202 if damage == "scope" else 101,
            "sources": [row],
        },
    )
    page = {"tenant_id": 101, "source_count": 2 if damage == "count" else 1, "ref": leaf}
    inner = await put(
        value,
        {
            "schema_version": 1,
            "semantic_contract": DIRECTORY,
            "pages": [page, page] if damage == "duplicate" else [page],
        },
    )
    directory = await put(
        value,
        {
            "schema_version": 1,
            "semantic_contract": DIRECTORY,
            "pages": [{"tenant_id": None, "source_count": 1, "ref": inner}],
        },
    )
    if damage == "missing_leaf":
        del value.artifacts.objects[leaf["object_key"]]
    if damage is not None:
        with pytest.raises(BaseErrorCode):
            await load_semantics(value.artifacts.store, value.frozen, directory)
    else:
        loaded = await load_semantics(value.artifacts.store, value.frozen, directory)
        assert list(loaded) == [SourceKey(**row["key"])]


async def test_candidate_is_complete_readonly_and_consumed_by_full_native_entry(published_input):
    value = published_input
    application = await prepared(value)
    await run_registration(application, apply=True, **value.input, operator_id=7)
    writes = []

    def observe(conn, cursor, sql, params, context, many):
        if sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            writes.append(sql)

    sa.event.listen(value.database.engine.sync_engine, "before_cursor_execute", observe)
    try:
        result = await inspect_reference_reconciliation(
            application, frozen=value.frozen, environment=value.input["environment"]
        )
    finally:
        sa.event.remove(value.database.engine.sync_engine, "before_cursor_execute", observe)
    assert result["manifest"] and not result["diagnostics"] and not writes
    ref = await put(value, result["manifest"])
    report = await application.arun_references(**value.input, operator_id=7, reconciliation_ref=ref)
    assert report.complete


async def test_baseline_frozen_candidate_checks_real_before_and_survives_its_own_conversion(published_input):
    value = published_input
    application = app(value)
    result = await inspect_reference_reconciliation(
        application, frozen=value.frozen, environment=value.input["environment"]
    )
    assert result["checked_before"] and result["manifest"] and not result["diagnostics"]
    ref = await put(value, result["manifest"])
    report = await application.arun_references(**value.input, operator_id=7, reconciliation_ref=ref)
    assert report.complete
    assert await application.arun_references(**value.input, operator_id=7, reconciliation_ref=ref) == report
