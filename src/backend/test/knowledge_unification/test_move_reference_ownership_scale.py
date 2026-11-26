"""§119 native target/slot scaling, real SQL bindings and validation counts."""

import pytest
import sqlalchemy as sa

from test.knowledge_unification import test_move_reference_ownership as base
from test.knowledge_unification.test_move_execution_fixtures import logical, pipeline

store, tenant, moving, accepted = base.store, base.tenant, base.moving, base.accepted


@pytest.mark.parametrize("count", [401, 10001])
@pytest.mark.parametrize("slots", [1, 3])
async def test_many_reference_rows_add_no_sql_to_business_move(moving, accepted, monkeypatch, count, slots):
    built = await pipeline(moving, accepted, monkeypatch)
    ids = tuple(row.file_id for row in built.confirmed.scope.files)
    assert len(ids) == 3
    # Two different real sources, multiple slots per exact target, without a Source by Target scan.
    rows = [
        base.binding(n + 1, file_id, source_id=f"source-{slot % 2}")
        for n, (file_id, slot) in enumerate(
            (ids[index % len(ids)], slot) for index in range(count) for slot in range(slots)
        )
    ]
    await base.seed(built, rows=rows)
    statements = []

    def capture(connection, cursor, statement, parameters, context, many):
        statements.append(statement)

    async with built.sessions() as session, session.begin():
        engine = session.bind.sync_engine
        sa.event.listen(engine, "before_cursor_execute", capture)
        try:
            receipt = await logical(session, built)
            await base.mark(session, built, receipt)
        finally:
            sa.event.remove(engine, "before_cursor_execute", capture)
    assert not [sql for sql in statements if "business_resource_reference" in sql or "business_reference_set" in sql]
    async with built.sessions() as session:
        persisted = (await session.execute(sa.select(base.BRR.__table__).order_by(base.BRR.id))).mappings().all()
        assert len(persisted) == count * slots and {row["target_space_id"] for row in persisted} == {"10"}
        files = (await session.execute(sa.select(base.File.knowledge_id).where(base.File.id.in_(ids)))).scalars().all()
        assert files == [11] * len(ids)
