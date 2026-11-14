"""Native bounded KN reads; SQLite does not prove MySQL/DM8 lock scheduling."""

import json
import math
import re
from dataclasses import replace

import pytest
import sqlalchemy as sa
from sqlmodel import Session

from bisheng.common.errcode.knowledge import ResourceReferenceConflictError, ResourceReferenceInvalidError
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.repositories import reference_target_repository as module
from bisheng.resource_reference.application.contracts import SourceKey, TargetKey
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference as Binding
from test.knowledge_unification import test_knowledge_target_scale as scale

owner_tenant = scale.owner_tenant
engine = scale.engine
SOURCE = scale.SOURCE


def binding(ident, *, source=SOURCE, slot="slot", kind="knowledge_file", owner=101, space="1", **extra):
    return {
        "tenant_id": source.tenant_id,
        "source_type": source.source_type.value,
        "source_id": source.source_id,
        "source_version": source.source_version,
        "slot_key": slot,
        "source_revision": 1,
        "target_type": kind,
        "target_id": str(ident),
        "target_tenant_id": owner,
        "target_space_id": space,
        **extra,
    }


class Reads(scale.Reads):
    def __init__(self, session):
        super().__init__(session)
        self.sql, self.original_pages, self.locks = [], [], []

    def cursor(self, conn, cursor, sql, params, context, many):
        super().cursor(conn, cursor, sql, params, context, many)
        if sql.lstrip().upper().startswith("SELECT"):
            self.sql.append((sql, params))

    def result(self, state):
        if not state.is_select:
            return None
        entity = state.statement.column_descriptions[0].get("entity")
        if entity in (Knowledge, KnowledgeFile) and state.statement._for_update_arg is not None:
            self.locks.append((entity, tuple(state.statement.compile().params["id_1"])))
        if entity is Binding:
            # Observe actual ORM rows from the actual SQL, retaining its order.
            frozen = state.invoke_statement().freeze()
            self.original_pages.append(tuple(frozen.data))
            return frozen()
        return None

    def __enter__(self):
        super().__enter__()
        sa.event.listen(self.session, "do_orm_execute", self.result, retval=True)
        return self

    def __exit__(self, *args):
        sa.event.remove(self.session, "do_orm_execute", self.result)
        super().__exit__(*args)

    def bounded(self):
        assert max((len(params) for _, params in self.sql), default=0) <= 800
        assert (
            max(
                (chunk.count("?") for sql, _ in self.sql for chunk in re.findall(r"\bIN\s*\(([^)]*)\)", sql)),
                default=0,
            )
            <= 200
        )
        assert all(tuple(sorted(ids)) == ids and len(ids) <= 200 for _, ids in self.locks)
        kinds = [kind for kind, _ in self.locks]
        assert not kinds or kinds == sorted(kinds, key=lambda kind: kind is KnowledgeFile)
        assert not self.session.new and not self.session.dirty and not self.session.deleted

    def report(self, **extra):
        print(
            json.dumps(
                {
                    **extra,
                    "selects": len(self.sql),
                    "original_selects": len(self.original_pages),
                    "original_rows": sum(map(len, self.original_pages)),
                    "original_max_page": max(map(len, self.original_pages), default=0),
                    "max_params": max((len(params) for _, params in self.sql), default=0),
                }
            )
        )


@pytest.mark.parametrize("count", [401, 1001, 10001])
async def test_native_async_bind_reads_complete_originals_once_per_key(count, monkeypatch):
    candidates, actual = [], module.original_for

    def observe(rows, key):
        candidates.append(len(rows))
        return actual(rows, key)

    monkeypatch.setattr(module, "original_for", observe)
    async with scale.native(count) as (session, ids):
        await session.execute(
            sa.insert(Binding.__table__), [binding(ident, slot=f"slot-{slot}") for ident in ids for slot in range(3)]
        )
        keys = tuple(TargetKey("knowledge_file", ident) for ident in reversed(ids))
        with Reads(session) as reads:
            result = await module.KnowledgeReferenceTargetRepository().alock_targets(session, keys, SOURCE, "bind")
        reads.report(path="async_bind", count=count, original_candidates=sum(candidates))
        scale.assert_observations(result, ids)
        assert len(candidates) == count and sum(candidates) == 3 * count
        assert len(reads.original_pages) == math.ceil(count / 200)
        assert sum(map(len, reads.original_pages)) == 3 * count
        assert all(row.original.slot_key == "slot-0" for row in result)
        reads.bounded()


@pytest.mark.parametrize("path", ["bind", "prelock"])
def test_native_sync_10001_is_successful_with_bounded_business_and_original_sql(engine, path):
    ids, data = scale.rows(10001)
    with Session(engine) as session, session.begin():
        for model, values in data:
            session.execute(sa.insert(model.__table__), values)
        session.execute(sa.insert(Binding.__table__), [binding(ident) for ident in ids])
    with Session(engine) as session, session.begin():
        repo, keys = module.KnowledgeReferenceTargetRepository(), tuple(TargetKey("knowledge_file", i) for i in ids)
        with Reads(session) as reads:
            if path == "prelock":
                repo.prelock_targets(session, keys, (SOURCE,))
                assert len(session.info[repo._prelock_key][2]) == len(ids)
            else:
                scale.assert_observations(repo.lock_targets(session, keys, SOURCE, "bind"), ids)
        reads.report(path="sync_" + path, count=len(ids))
        assert len(reads.original_pages) == 51
        assert sum(map(len, reads.original_pages)) == len(ids)
        reads.bounded()


async def test_native_async_10001_prelock_uses_real_pk_pages():
    async with scale.native(10001) as (session, ids):
        await session.execute(sa.insert(Binding.__table__), [binding(ident) for ident in ids])
        repo, keys = module.KnowledgeReferenceTargetRepository(), tuple(TargetKey("knowledge_file", i) for i in ids)
        with Reads(session) as reads:
            await repo.aprelock_targets(session, keys, (SOURCE,))
        reads.report(path="async_prelock", count=len(ids))
        assert len(session.info[repo._prelock_key][2]) == len(ids)
        assert len(reads.original_pages) == 51 and sum(map(len, reads.original_pages)) == len(ids)
        assert max(map(len, reads.original_pages)) <= 200
        reads.bounded()


@pytest.mark.parametrize("count", [401, 1001])
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_selected_sparse_versions_do_not_multiply_versions_by_union_targets(engine, count, asynchronous):
    sources = tuple(replace(SOURCE, source_version=f"version-{i:05}") for i in range(count))

    async def exercise(session, ids):
        values = [binding(ident, source=source) for ident, source in zip(ids, sources, strict=True)]
        if asynchronous:
            await session.execute(sa.insert(Binding.__table__), values)
        else:
            session.execute(sa.insert(Binding.__table__), values)
        repo, keys = module.KnowledgeReferenceTargetRepository(), tuple(TargetKey("knowledge_file", i) for i in ids)
        with Reads(session) as reads:
            if asynchronous:
                await repo.aprelock_targets(session, keys, tuple(reversed(sources)))
            else:
                repo.prelock_targets(session, keys, tuple(reversed(sources)))
        reads.report(path="sparse_async" if asynchronous else "sparse_sync", versions=count, bindings=count)
        assert len(reads.original_pages) <= math.ceil(count / 200) + count // 200
        assert sum(map(len, reads.original_pages)) == count
        assert max(map(len, reads.original_pages)) <= 200
        assert {row.source_version for page in reads.original_pages for row in page} == {
            source.source_version for source in sources
        }
        assert len(session.info[repo._prelock_key][2]) == count
        reads.bounded()

    if asynchronous:
        async with scale.native(count) as (session, ids):
            await exercise(session, ids)
    else:
        ids, data = scale.rows(count)
        with Session(engine) as session, session.begin():
            for model, values in data:
                session.execute(sa.insert(model.__table__), values)
        with Session(engine) as session, session.begin():
            await exercise(session, ids)


@pytest.mark.parametrize("raw_count", [200, 401])
async def test_raw_pk_progresses_through_unselected_invalid_targets_and_filters_versions(raw_count):
    async with scale.native() as (session, ids):
        values = [binding(ids[0])] + [binding(f"bad-{i}", space="invalid") for i in range(raw_count - 1)]
        values += [
            binding(ids[0], source=replace(SOURCE, source_version="not-selected"), space="invalid"),
            binding(ids[0], source=replace(SOURCE, source_id="not-selected"), space="invalid"),
            binding(ids[0], source=SourceKey(202, "assistant", SOURCE.source_id, "current"), space="invalid"),
            binding(ids[0], kind="model", space="invalid"),
        ]
        with bypass_tenant_filter():
            await session.execute(sa.insert(Binding.__table__), values)
        repo, key = module.KnowledgeReferenceTargetRepository(), TargetKey("knowledge_file", ids[0])
        with Reads(session) as reads:
            await repo.aprelock_targets(session, (key,), (SOURCE,))
        assert [len(page) for page in reads.original_pages] == ([200, 0] if raw_count == 200 else [200, 200, 1])
        assert all(row.source_version == "current" and row.tenant_id == 101 for p in reads.original_pages for row in p)
        assert session.info[repo._prelock_key][3] == frozenset({1})
        reads.bounded()


async def test_exact_type_id_pairs_and_version_specific_evidence_do_not_cross():
    async with scale.native(2) as (session, ids):
        first, second = replace(SOURCE, source_version="first"), replace(SOURCE, source_version="second")
        await session.execute(
            sa.insert(Binding.__table__),
            [
                binding(ids[0], source=first, slot="one", space="1"),
                binding(ids[0], source=first, slot="two", space="1"),
                binding(ids[0], source=second, space="2"),
                binding(1, source=first, kind="knowledge_space"),
                binding(ids[0], source=first, kind="knowledge_space", space="invalid"),
                binding(1, source=first, space="invalid"),
            ],
        )
        await session.execute(sa.delete(KnowledgeFile.__table__).where(KnowledgeFile.id == ids[0]))
        repo, keys = (
            module.KnowledgeReferenceTargetRepository(),
            (
                TargetKey("knowledge_space", 1),
                TargetKey("knowledge_file", ids[0]),
            ),
        )
        await repo.aprelock_targets(session, keys, (first, second))
        for source, space in ((first, "1"), (second, "2")):
            with Reads(session) as reads:
                result = await repo.alock_targets(session, keys, source, "bind")
            assert result[1].original.source_version == source.source_version and result[1].target_space_id == space
            assert all(
                (row.target_type, row.target_id) in {(key.target_type.value, key.target_id) for key in keys}
                for page in reads.original_pages
                for row in page
            )
        with pytest.raises(ResourceReferenceConflictError):
            await repo.alock_targets(session, keys, replace(SOURCE, source_version="not-locked"), "bind")


@pytest.mark.parametrize(
    "change",
    [
        {"target_tenant_id": 202},
        {"target_space_id": "2"},
        {"legacy_invalid_reason": "target_missing", "legacy_run_id": "r", "legacy_evidence_key": "e"},
    ],
)
async def test_multislot_conflicts_keep_the_original_five_field_check(change):
    async with scale.native() as (session, ids):
        await session.execute(sa.insert(Binding.__table__), [binding(ids[0], slot=f"slot-{i}") for i in range(3)])
        await session.execute(sa.update(Binding.__table__).where(Binding.slot_key == "slot-2").values(**change))
        with pytest.raises(ResourceReferenceInvalidError):
            await module.KnowledgeReferenceTargetRepository().alock_targets(
                session, (TargetKey("knowledge_file", ids[0]),), SOURCE, "bind"
            )


async def test_orm_refresh_empty_no_sql_and_foreign_source_rejection_remain_native():
    async with scale.native() as (session, ids):
        await session.execute(sa.insert(Binding.__table__), binding(ids[0]))
        cached = (await session.execute(sa.select(Binding))).scalar_one()
        connection = await session.connection()
        await connection.execute(sa.update(Binding.__table__).values(source_revision=9))
        repo, key = module.KnowledgeReferenceTargetRepository(), TargetKey("knowledge_file", ids[0])
        result = await repo.alock_targets(session, (key,), SOURCE, "bind")
        assert result[0].original is cached and cached.source_revision == 9
        with Reads(session) as reads:
            assert await repo.alock_targets(session, (), SOURCE, "bind") == ()
            await repo.aprelock_targets(session, (), (SOURCE,))
            with pytest.raises(ResourceReferenceInvalidError):
                await repo.alock_targets(session, (key,), replace(SOURCE, tenant_id=202), "bind")
        assert not reads.sql
