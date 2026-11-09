"""T1011: real many-member/many-Root writes retain bounded indexed locking."""

import math
import re
from collections import Counter

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain.repositories.unification_space_membership_repository import SpaceMembershipRow
from bisheng.knowledge.domain.services.unification_conversion import UnificationConversionService
from test.knowledge_unification.test_migration_membership_writer import Member, commands, issue, member, original
from test.knowledge_unification.test_migration_membership_writer import database as database
from test.knowledge_unification.test_migration_membership_writer import resource_native as resource_native


@pytest.mark.parametrize(("root_count", "member_count"), [(1, 401), (1, 10001), (401, 401), (10001, 10001)])
async def test_real_producer_writer_pages_member_sets_once_and_does_not_scan_per_root(
    database, monkeypatch, root_count, member_count
):
    root_ids = [9000, *(10000 + i for i in range(root_count - 1))]
    if root_count > 1:
        await database.insert(original.raw.Knowledge, [original.raw.resource(ident) for ident in root_ids[1:]])
    await database.insert(
        Member,
        [
            member(i + 1, str(root_ids[i % root_count]), user_id=8, user_role="MEMBER", status="REJECTED")
            for i in range(member_count)
        ],
    )
    values = await commands(database)
    assert len(values) == root_count
    service = UnificationConversionService()
    getattribute, bound = SpaceMembershipRow.__getattribute__, service.repository._bound
    field_reads, seals, statements = Counter(), [], []

    def tracked(row, name):
        if name in SpaceMembershipRow.__dataclass_fields__:
            field_reads[getattribute(row, "id")] += 1
        return getattribute(row, name)

    def guarded(*args, **kwargs):
        seals.append(1)
        return bound(*args, **kwargs)

    def capture(_c, _cu, sql, params, _ctx, _many):
        statements.append((sql, params))

    monkeypatch.setattr(SpaceMembershipRow, "__getattribute__", tracked)
    monkeypatch.setattr(service.repository, "_bound", guarded)
    sa.event.listen(database.engine.sync_engine, "before_cursor_execute", capture)
    continuation, current = None, None
    try:
        for start in range(0, root_count, 200):
            batch = values[start : start + 200]
            async with AsyncSession(database.engine) as session, session.begin():
                continuation = await service.aapply_batch(
                    session,
                    batch=await issue(
                        service,
                        session,
                        batch,
                        ordinal=start,
                        expected_checkpoint=current,
                        continuation=continuation,
                        eof=start + len(batch) == root_count,
                    ),
                )
                current = continuation.progress
    finally:
        sa.event.remove(database.engine.sync_engine, "before_cursor_execute", capture)
    async with database.engine.connect() as connection:
        creators = (
            await connection.execute(sa.select(sa.func.count()).select_from(Member).where(Member.user_id == 7))
        ).scalar_one()
    assert creators == root_count and current.complete
    member_queries = [(sql, params) for sql, params in statements if "FROM space_channel_member" in sql]
    assert member_queries and all(
        "LIMIT" in sql and "ORDER BY space_channel_member.id" in sql for sql, _ in member_queries
    )
    assert all(len(params) <= 204 for _, params in member_queries)
    assert all("CAST(" not in sql.upper() for sql, _ in member_queries)
    for sql, _ in member_queries:
        for fragment in re.findall(r"\bIN\s*\(([^)]*)\)", sql):
            assert fragment.count("?") <= 200
    assert len(seals) <= 10 * math.ceil(root_count / 200)
    assert max(field_reads.values()) <= 180
    if root_count == 1:
        assert len(member_queries) <= 3 * math.ceil((member_count + 1) / 200) + 3
    else:
        assert len(member_queries) <= 6 * math.ceil(root_count / 200)
    print(
        {
            "roots": root_count,
            "before_members": member_count,
            "member_selects": len(member_queries),
            "max_params": max(len(p) for _, p in member_queries),
            "full_scope_seals": len(seals),
            "max_field_reads_per_pk": max(field_reads.values()),
        }
    )
