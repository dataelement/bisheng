"""Invalid saved configurations remain audited and unusable, never guessed IDs."""

import pytest
import sqlalchemy as sa
from sqlmodel import select

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.knowledge.application.unification_coverage import production_coverage_factory
from bisheng.knowledge.domain.repositories.unification_inventory_repository import Flow, FlowVersion
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
from bisheng.workflow.domain.services.reference_extractor import extract_workflow_version_references
from test.knowledge_unification import test_migration_structural_retention as original
from test.knowledge_unification.test_migration_source_inventory import graph

resource_native, native, complete = original.resource_native, original.native, original.complete
raw_resource_native = original.raw_resource_native
transport, module, published_input = original.transport, original.module, original.published_input
no_real_network = original.reference_tests.no_real_network
ROOT = "invalid-saved-workflow"


def bad():
    return graph("FILL_MODEL_ID")


async def seed(database):
    await database.insert(
        Flow,
        [
            {
                "id": ROOT,
                "tenant_id": 101,
                "name": "saved",
                "user_id": 7,
                "flow_type": 10,
                "is_delete": 0,
                "data": graph(11),
            }
        ],
    )
    await database.insert(
        FlowVersion,
        [
            {
                "id": 71,
                "tenant_id": 101,
                "flow_id": ROOT,
                "name": "broken",
                "flow_type": 10,
                "is_current": 1,
                "is_delete": 0,
                "data": bad(),
            },
            {
                "id": 72,
                "tenant_id": 101,
                "flow_id": ROOT,
                "name": "good",
                "flow_type": 1,
                "is_current": 0,
                "is_delete": 0,
                "data": graph(11),
            },
        ],
    )


@pytest.mark.parametrize("published_input", [{"reference_seed": seed}], indirect=True)
async def test_full_migration_and_completed_resume_preserve_invalid_current_version_and_valid_old_tag(published_input):
    value = published_input
    result = await original.reference_tests.app(value).arun_references(**value.input, operator_id=7)
    assert (
        result.complete
        and await original.reference_tests.app(value).arun_references(**value.input, operator_id=7) == result
    )
    async with value.sessions() as session, session.begin():
        assert (await session.get(FlowVersion, 71)).data == bad()
        assert (await session.get(FlowVersion, 71)).is_current == 1
        assert (await session.get(Flow, ROOT)).data == graph(11)
        heads = (
            await session.exec(
                select(BusinessReferenceSet).where(
                    BusinessReferenceSet.source_type == "workflow_version",
                    BusinessReferenceSet.source_id == ROOT,
                    BusinessReferenceSet.record_kind == "source",
                )
            )
        ).all()
        assert {row.source_version for row in heads if row.ready} == {"72"}
        assert (await production_coverage_factory(session).arequire_global_ready()).verified_tenant_ids
    with pytest.raises(ValueError):
        extract_workflow_version_references(bad())


@pytest.mark.parametrize("published_input", [{"reference_seed": seed}], indirect=True)
@pytest.mark.parametrize("change", ["repair", "flag", "root"])
async def test_changed_quarantine_facts_refuse_original_frozen_run(published_input, change):
    value = published_input
    async with value.database.engine.begin() as connection:
        if change == "repair":
            await connection.execute(sa.update(FlowVersion).where(FlowVersion.id == 71).values(data=graph(11)))
        elif change == "flag":
            await connection.execute(sa.update(FlowVersion).where(FlowVersion.id == 71).values(is_current=0))
        else:
            await connection.execute(sa.update(Flow).where(Flow.id == ROOT).values(data=graph(12)))
    with pytest.raises(BaseErrorCode):
        await original.reference_tests.app(value).arun_references(**value.input, operator_id=7)


async def seed_missing_creator(database):
    await seed(database)
    async with database.engine.begin() as connection:
        await connection.execute(sa.update(Flow).where(Flow.id == ROOT).values(user_id=999))


@pytest.mark.parametrize("published_input", [{"reference_seed": seed_missing_creator}], indirect=True)
async def test_invalid_version_and_missing_creator_proofs_compose_without_new_identity(published_input):
    value = published_input
    assert (await original.reference_tests.app(value).arun_references(**value.input, operator_id=7)).complete


def bad_selection():
    return {
        "nodes": [
            {
                "data": {
                    "id": "rag-old",
                    "type": "rag",
                    "group_params": [
                        {
                            "params": [
                                {"key": "knowledge", "value": {"type": "knowledge", "value": ["input_old.user_input"]}}
                            ]
                        }
                    ],
                }
            }
        ],
        "edges": [],
    }


async def seed_selection(database):
    await seed(database)
    async with database.engine.begin() as connection:
        await connection.execute(
            sa.update(FlowVersion).where(FlowVersion.id == 71).values(data=bad_selection(), flow_type=1, is_current=0)
        )


@pytest.mark.parametrize("published_input", [{"reference_seed": seed_selection}], indirect=True)
async def test_legacy_noncurrent_selection_is_retained_without_guessing_knowledge_id(published_input):
    value = published_input
    assert (await original.reference_tests.app(value).arun_references(**value.input, operator_id=7)).complete
    async with value.sessions() as session, session.begin():
        assert (await session.get(FlowVersion, 71)).data == bad_selection()
    with pytest.raises(ValueError):
        extract_workflow_version_references(bad_selection())


async def test_existing_index_on_invalid_configuration_is_a_true_blocker(complete):
    from sqlmodel.ext.asyncio.session import AsyncSession

    from bisheng.core.context.tenant import tenant_execution_scope
    from bisheng.knowledge.application.unification_sources import UnificationSourceInventory
    from test.knowledge_unification.test_migration_source_inventory import sharing

    await seed(complete)
    await complete.insert(
        BusinessReferenceSet,
        [
            {
                "tenant_id": 101,
                "source_type": "workflow_version",
                "source_id": ROOT,
                "source_version": "71",
                "record_kind": "source",
                "extractor_version": "workflow-version-v1",
                "digest": "a" * 64,
                "ready": True,
            }
        ],
    )
    with tenant_execution_scope(101):
        async with AsyncSession(complete.engine) as session, session.begin(), sharing() as (reader, _):
            inventory = UnificationSourceInventory(sharing_reader=reader)
            with pytest.raises(BaseErrorCode) as error:
                async for _ in inventory.aiter_tenant_source_records(
                    session, run_id="retention-test", writer_contract_version="f118-v1"
                ):
                    pass
            assert error.value.kwargs["reason"] == "unification_sources_invalid_workflow_configuration_has_index"


async def seed_many(database, count):
    for i in range(count):
        root = f"{ROOT}-{i}"
        await database.insert(
            Flow,
            [
                {
                    "id": root,
                    "tenant_id": 101,
                    "name": "saved",
                    "user_id": 7,
                    "flow_type": 10,
                    "is_delete": 0,
                    "data": graph(11),
                }
            ],
        )
        await database.insert(
            FlowVersion,
            [
                {
                    "id": 171 + i,
                    "tenant_id": 101,
                    "flow_id": root,
                    "name": "broken",
                    "flow_type": 10,
                    "is_current": 1,
                    "is_delete": 0,
                    "data": bad(),
                }
            ],
        )
    database.queries.clear()


async def seed_two(database):
    await seed_many(database, 2)


async def seed_four(database):
    await seed_many(database, 4)


@pytest.mark.parametrize(
    "published_input", [{"reference_seed": seed_two}, {"reference_seed": seed_four}], indirect=True
)
async def test_complete_preview_apply_verify_resume_scale(published_input, record_property):
    import time

    value = published_input
    started = time.monotonic()
    first = await original.reference_tests.app(value).arun_references(**value.input, operator_id=7)
    assert (
        first.complete
        and await original.reference_tests.app(value).arun_references(**value.input, operator_id=7) == first
    )
    record_property(
        "scale",
        str(
            {
                "sql_including_preview": len(value.database.queries),
                "seconds_apply_verify_resume": round(time.monotonic() - started, 3),
            }
        ),
    )
