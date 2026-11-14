"""Native M2/M3/M4 retain original invalid sources without granting authority."""

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession
from test.knowledge_unification.test_migration_references_application import (
    app,
)
from test.knowledge_unification.test_migration_references_application import (
    complete as complete,
)
from test.knowledge_unification.test_migration_references_application import (
    native as native,
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
from test.knowledge_unification.test_migration_source_inventory import graph

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.database.models.flow import Flow
from bisheng.database.models.flow_version import FlowVersion
from bisheng.knowledge.domain.models.knowledge_unification_run import KnowledgeUnificationRun
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference


async def seed_history(database):
    async with AsyncSession(database.engine) as session, session.begin():
        with bypass_tenant_filter():
            session.add_all(
                [
                    Flow(id="foreign-parent", tenant_id=202, user_id=7, name="foreign", flow_type=10),
                    Flow(id="legacy-version", tenant_id=101, user_id=7, name="legacy tag", flow_type=10),
                    Flow(id="other-domain", tenant_id=101, user_id=7, name="legacy flow", flow_type=1),
                    FlowVersion(
                        id=81,
                        flow_id="foreign-parent",
                        tenant_id=202,
                        name="corrected owner",
                        flow_type=10,
                        data=graph(11, 9000),
                    ),
                    FlowVersion(
                        id=82,
                        flow_id="absent-parent",
                        tenant_id=101,
                        name="deleted",
                        flow_type=10,
                        is_delete=1,
                        data=graph(11, 9000),
                    ),
                    FlowVersion(
                        id=83,
                        flow_id="legacy-version",
                        tenant_id=101,
                        name="old tag",
                        flow_type=1,
                        data=graph(11, 9000),
                    ),
                    FlowVersion(
                        id=84,
                        flow_id="other-domain",
                        tenant_id=101,
                        name="out of scope",
                        flow_type=1,
                        data={"nodes": [], "edges": []},
                    ),
                ]
            )


@pytest.mark.parametrize("published_input", [{"reference_seed": seed_history}], indirect=True)
async def test_aligned_versions_and_deleted_history_remain_unchanged_through_m4_and_resume(published_input):
    value = published_input
    async with value.sessions() as session, session.begin():
        before = (
            (
                await session.execute(
                    sa.select(FlowVersion.__table__)
                    .where(FlowVersion.id.in_((81, 82, 83, 84)))
                    .order_by(FlowVersion.id)
                )
            )
            .mappings()
            .all()
        )
    assert (await app(value).arun_references(**value.input, operator_id=7)).complete
    async with value.sessions() as session, session.begin():
        after = (
            (
                await session.execute(
                    sa.select(FlowVersion.__table__)
                    .where(FlowVersion.id.in_((81, 82, 83, 84)))
                    .order_by(FlowVersion.id)
                )
            )
            .mappings()
            .all()
        )
        assert before == after
        for model in (BusinessResourceReference, BusinessReferenceSet):
            assert not (
                await session.execute(sa.select(model.id).where(model.source_id.in_(("absent-parent", "other-domain"))))
            ).all()
        refs = (
            (
                await session.execute(
                    sa.select(BusinessResourceReference.__table__).where(
                        BusinessResourceReference.source_id == "legacy-version"
                    )
                )
            )
            .mappings()
            .all()
        )
        assert len(refs) == 2 and {row["target_id"] for row in refs} == {"11", "9000"}
        run = (
            (
                await session.execute(
                    sa.select(KnowledgeUnificationRun.__table__).where(KnowledgeUnificationRun.tenant_id == 101)
                )
            )
            .mappings()
            .one()
        )
        assert run["phase"] == "completed" and run["source_coverage"]["workflow_version"]
    assert (await app(value).arun_references(**value.input, operator_id=7)).complete


@pytest.mark.parametrize("change", ["parent_owner", "version_payload", "revive_deleted"])
@pytest.mark.parametrize("published_input", [{"reference_seed": seed_history}], indirect=True)
async def test_invalid_source_facts_cannot_be_reclassified_after_freeze(published_input, change):
    value = published_input
    async with value.sessions() as session, session.begin():
        with bypass_tenant_filter():
            if change == "parent_owner":
                await session.execute(sa.update(Flow).where(Flow.id == "foreign-parent").values(tenant_id=101))
            elif change == "version_payload":
                await session.execute(sa.update(FlowVersion).where(FlowVersion.id == 81).values(data=graph(11, 9999)))
            else:
                await session.execute(sa.update(FlowVersion).where(FlowVersion.id == 82).values(is_delete=0))
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await app(value).arun_references(**value.input, operator_id=7)


async def seed_history_with_index(database):
    from bisheng.resource_reference.application.contracts import reference_set_digest

    await seed_history(database)
    async with AsyncSession(database.engine) as session, session.begin():
        session.add(
            BusinessReferenceSet(
                tenant_id=101,
                source_type="workflow_version",
                source_id="foreign-parent",
                source_version="__root__",
                record_kind="root_guard",
                source_revision=1,
                extractor_version="root-guard-v1",
                digest=reference_set_digest(()),
                ready=False,
                effective=False,
            )
        )


async def test_retained_invalid_source_cannot_discard_an_existing_index(complete, transport, monkeypatch):
    from test.knowledge_unification.test_migration_source_lifecycle import freeze

    with pytest.raises(KnowledgeOperationPlanConflictError) as error:
        await freeze(complete, transport, monkeypatch, seed_history_with_index)
    assert error.value.kwargs["reason"] == "unification_inventory_unknown_absent_root"
