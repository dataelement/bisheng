"""The original M3 entry must reach real backfill, verification and Coverage."""

import sqlalchemy as sa

from bisheng.knowledge.application.unification_coverage import production_coverage_factory
from bisheng.knowledge.domain.models.knowledge_unification_run import KnowledgeUnificationRun as Run
from bisheng.resource_reference.application.contracts import SourceType
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
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


async def test_actual_original_entry_completes_references_and_production_coverage(published_input):
    value = published_input
    result = await app(value).arun_references(**value.input, operator_id=7)
    assert result.complete and result.run_id == value.frozen.run_id
    value.sessions.assert_closed()
    async with value.sessions() as session, session.begin():
        rows = (await session.execute(sa.select(Run).order_by(Run.tenant_id))).scalars().all()
        assert all(row.phase == "completed" and row.coverage_epoch > 0 for row in rows)
        assert all(row.source_coverage == {kind.value: True for kind in SourceType} for row in rows)
        sources = (
            (await session.execute(sa.select(BusinessReferenceSet).where(BusinessReferenceSet.record_kind == "source")))
            .scalars()
            .all()
        )
        assert sources and all(row.ready for row in sources)
        repository = production_coverage_factory(session)
        assert len(await repository.arequire_ready()) == 6
        global_ready = await repository.arequire_global_ready()
        assert global_ready.verified_tenant_ids == value.frozen.tenant_ids
    assert await app(value).arun_references(**value.input, operator_id=7) == result
