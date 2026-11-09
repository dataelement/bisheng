"""T1005: actual many-root membership capture and candidate budgets."""

from math import ceil

import pytest

from test.knowledge_unification import test_migration_membership_producer as producer

resource_native, native, complete = producer.resource_native, producer.native, producer.complete


@pytest.mark.parametrize("count", [401, 10001])
async def test_native_member_reads_and_plan_candidates_follow_root_pages_not_roots_squared(
    complete, monkeypatch, count
):
    await complete.insert(
        producer.original.original.Knowledge, [producer.original.original.resource(1000 + i) for i in range(count)]
    )
    await complete.insert(
        producer.Member,
        [producer.member_fixture.member(i + 1, str(1000 + i), user_id=8, user_role="MEMBER") for i in range(count)],
    )
    module = __import__("bisheng.knowledge.application.unification_preflight", fromlist=["x"])
    planner, candidates = module.plan_space_creator_membership, []

    def planned(header, members, creator, **kwargs):
        candidates.append((header.knowledge_id, len(members)))
        return planner(header, members, creator, **kwargs)

    monkeypatch.setattr(module, "plan_space_creator_membership", planned)
    records, sql = await producer.collect(complete)
    headers = [row for _, row in records if row.record_type == "space_membership_header"]
    members = [row for _, row in records if row.record_type == "space_member"]
    commands = [row for _, row in records if row.record_type == "resource_conversion"]
    assert len(headers) == len(members) == len(commands) == len(candidates) == count
    assert len({ident for ident, _ in candidates}) == count and all(size == 1 for _, size in candidates)
    membership_sql = [
        (query, params) for query, params in sql if "space_channel_member" in query or "AS creator_user_id" in query
    ]
    assert len(membership_sql) == 4 * ceil(count / 200) + 1
    assert max(len(params) for _, params in membership_sql) <= 205
    assert len([row for _, row in records if row.record_type == "creator"]) == 1
    print(
        {
            "roots": count,
            "members": len(members),
            "member_sql": len(membership_sql),
            "plan_candidates": len(candidates),
            "max_parameters": max(len(params) for _, params in membership_sql),
        }
    )
