"""T983: native bounded global-ID merge keeps original Owner authority.

覆盖 AC: AC-28, AC-29, AC-72, AC-89, AC-90, AC-91, AC-94
SQLite checks actual SQL, receipts and transaction identity, not lock timing.
"""

import asyncio
import hashlib
from dataclasses import replace
from math import ceil

import pytest
from sqlalchemy import update

from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError, ResourceReferenceInvalidError
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.resource_reference.application.contracts import TargetKey, TransactionIdentity
from bisheng.resource_reference.domain.repositories.reference_repository import ReferenceRepository
from test.knowledge_unification import test_inbound_owner_stream as grouped
from test.knowledge_unification.test_inbound_owner_stream import Binding, SourceSet, native, observe
from test.knowledge_unification.test_ref_repo import tenant

owner_tenant = grouped.owner_tenant


async def consume(repository, session, scope, *, limit=200, global_id_order=True):
    return [
        page
        async for page in repository.aiter_inbound_for_owner_pages(
            session, scope, limit=limit, global_id_order=global_id_order
        )
    ]


@pytest.mark.parametrize(
    "count,slots,sparse",
    [
        (401, 0, False),
        (401, 3, False),
        (1001, 0, False),
        (1001, 3, False),
        (10001, 0, False),
        (10001, 1, True),
        (10001, 3, False),
    ],
)
async def test_native_global_sql_cpu_parameter_and_live_orm_bounds(monkeypatch, count, slots, sparse):
    async with native(count, slots=slots, sparse=sparse) as (session, repository, scope, seeded):
        digest, total, previous, peak = hashlib.sha256(), 0, 0, 0
        with observe(session, repository, monkeypatch) as (sql, validations, checks):
            async for page in repository.aiter_inbound_for_owner_pages(session, scope, global_id_order=True):
                assert type(page) is tuple and 0 < len(page) <= 200
                for row in page:
                    assert row.id > previous
                    previous = row.id
                    digest.update(row.id.to_bytes(8, "big"))
                total += len(page)
                peak = max(peak, sum(isinstance(row, Binding) for row in session.identity_map.values()))
        expected = hashlib.sha256()
        for ident in range(1, len(seeded) + 1):
            expected.update(ident.to_bytes(8, "big"))
        assert total == len(seeded) and digest.digest() == expected.digest()
        assert validations == [count, count] and len(checks) == 2
        assert ceil(count / 200) <= len(sql) <= ceil(count / 200) + len(seeded) // 200
        assert max(len(params) for _, params in sql) <= 250
        assert all(
            "LEFT OUTER JOIN" in query
            and "ORDER BY business_resource_reference.id" in query
            and query.lstrip().upper().startswith("SELECT")
            for query, _ in sql
        )
        assert peak <= ceil(count / 200) * 200 + 400
        assert not session.new and not session.dirty and not session.deleted
        print(
            {
                "targets": count,
                "references": total,
                "sql": len(sql),
                "validation": validations,
                "peak_live_bindings": peak,
            }
        )


@pytest.mark.parametrize("limit", [1, 37, 200])
async def test_interleaved_groups_equal_original_global_page_oracle_and_default_stays_grouped(limit):
    async with native(401, slots=3) as (session, repository, scope, seeded):
        # Interleave all three target groups in physical ID order, including
        # same-group page boundaries. Original native fixtures reverse groups.
        order = sorted(range(1, 402), key=lambda ident: ((ident - 1) % 200, ident))
        for start in range(0, len(seeded), 200):
            for offset, row in enumerate(seeded[start : start + 200], start):
                row["target_id"] = str(order[offset % 401])
        await session.execute(Binding.__table__.delete())
        await session.execute(Binding.__table__.insert(), seeded)
        expected, after = [], None
        while True:
            page = await repository.alist_inbound_for_owner_page(session, scope, after_id=after, limit=limit)
            if not page:
                break
            expected.extend((row.id, row.slot_key, row.target_id) for row in page)
            after = page[-1].id
        pages = await consume(repository, session, scope, limit=limit)
        assert [(row.id, row.slot_key, row.target_id) for page in pages for row in page] == expected
        assert all(0 < len(page) <= limit for page in pages)
        grouped = await consume(repository, session, scope, limit=limit, global_id_order=False)
        assert sorted(row.id for page in grouped for row in page) == [item[0] for item in expected]
        assert [row.id for page in grouped for row in page] != [item[0] for item in expected]


@pytest.mark.parametrize("flag", [None, 0, 1, "true", 1.0, (), object()])
async def test_order_mode_requires_strict_bool_before_sql(monkeypatch, flag):
    async with native() as (session, repository, scope, _):
        with observe(session, repository, monkeypatch) as (sql, _, _), pytest.raises(ValueError):
            await consume(repository, session, scope, global_id_order=flag)
        assert not sql


@pytest.mark.parametrize("failure", ["missing", "ready", "effective", "revision", "kind", "identity"])
async def test_global_join_preserves_incomplete_source_fail_closed(failure):
    async with native(201) as (session, repository, scope, _):
        if failure == "missing":
            await session.execute(SourceSet.__table__.delete())
        else:
            values = {
                "ready": {"ready": False},
                "effective": {"effective": False},
                "revision": {"source_revision": 99},
                "kind": {"record_kind": "root_guard", "source_version": "__root__", "ready": False, "effective": False},
                "identity": {"tenant_id": 202},
            }[failure]
            await session.execute(update(SourceSet.__table__).values(**values))
        with pytest.raises(ReferenceCoverageNotReadyError):
            await consume(repository, session, scope)


@pytest.mark.parametrize("failure", ["copy", "issuer", "tx", "tenant", "bypass"])
async def test_global_start_rejects_original_scope_and_identity_violations(monkeypatch, failure):
    async with native(201) as (session, repository, scope, _):
        if failure == "copy":
            scope = replace(scope)
        elif failure == "issuer":
            repository = ReferenceRepository(verifier=repository.verifier)
        elif failure == "tx":
            await session.commit()
            await session.begin()
        with observe(session, repository, monkeypatch) as (sql, _, _), pytest.raises(ResourceReferenceInvalidError):
            if failure == "tenant":
                with tenant(202):
                    await consume(repository, session, scope)
            elif failure == "bypass":
                with bypass_tenant_filter():
                    await consume(repository, session, scope)
            else:
                await consume(repository, session, scope)
        assert not sql


@pytest.mark.parametrize("failure", ["scope", "alias", "tx", "tenant", "bypass", "registration", "authority", "owner"])
async def test_buffered_pages_never_hide_changed_identity_or_redirect_next_sql(monkeypatch, failure):
    async with native(401) as (session, repository, scope, _):
        stream = repository.aiter_inbound_for_owner_pages(session, scope, limit=1, global_id_order=True)
        with observe(session, repository, monkeypatch) as (sql, validations, _):
            assert len(await anext(stream)) == 1
            before = len(sql)
            if failure == "scope":
                object.__setattr__(scope, "targets", (TargetKey("knowledge_file", 999999),))
            elif failure == "alias":
                object.__setattr__(scope.targets[-1], "target_id", "999999")
            elif failure == "tx":
                await session.commit()
                await session.begin()
                object.__setattr__(scope, "transaction", TransactionIdentity.capture(session))
            elif failure == "registration":
                del repository._issued_scopes[scope]
            elif failure == "authority":
                object.__setattr__(scope, "_authority", object())
            elif failure == "owner":
                object.__setattr__(scope, "owner_tenant_id", 202)
            with pytest.raises(ResourceReferenceInvalidError):
                if failure == "tenant":
                    with tenant(202):
                        _ = [page async for page in stream]
                elif failure == "bypass":
                    with bypass_tenant_filter():
                        _ = [page async for page in stream]
                else:
                    _ = [page async for page in stream]
            assert all("999999" not in tuple(map(str, params)) for _, params in sql)
            if failure not in {"scope", "alias"}:
                assert len(sql) == before and validations == [401]
        await stream.aclose()


@pytest.mark.parametrize("ending", ["close", "cancel"])
async def test_global_partial_or_cancel_never_gets_final_scope_validation(monkeypatch, ending):
    async with native(401) as (session, repository, scope, _):
        stream = repository.aiter_inbound_for_owner_pages(session, scope, limit=37, global_id_order=True)
        with observe(session, repository, monkeypatch) as (_, validations, checks):
            if ending == "close":
                assert len(await anext(stream)) == 37
                await stream.aclose()
            else:
                entered, hold = asyncio.Event(), asyncio.Event()

                async def read():
                    try:
                        async for _page in stream:
                            entered.set()
                            await hold.wait()
                    finally:
                        await stream.aclose()

                task = asyncio.create_task(read())
                await entered.wait()
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            assert validations == [401] and len(checks) == 1


async def test_global_captures_buffered_ids_and_seek_before_yield_without_autoflush(monkeypatch):
    async with native(401) as (session, repository, scope, _):
        pending = SourceSet(
            tenant_id=101,
            source_type="assistant",
            source_id="pending",
            source_version="current",
            source_revision=1,
            extractor_version="native",
            digest="b" * 64,
            ready=True,
            effective=True,
        )
        session.add(pending)
        stream = repository.aiter_inbound_for_owner_pages(session, scope, limit=37, global_id_order=True)
        with observe(session, repository, monkeypatch) as (sql, validations, _):
            first = await anext(stream)
            assert [row.id for row in first] == list(range(1, 38))
            # The remaining buffered page has IDs beyond this caller-owned
            # row. A later SQL must seek its captured ID, never this new value.
            first[-1].id = 999999
            remaining = [row.id async for page in stream for row in page]
            assert remaining == list(range(38, 402))
        assert pending in session.new and pending.id is None and first[-1] in session.dirty
        assert validations == [401, 401]
        assert all(query.lstrip().upper().startswith("SELECT") for query, _ in sql)


async def test_cancel_during_native_prefetch_never_validates_completion_or_commits(monkeypatch):
    async with native(401) as (session, repository, scope, _):
        execute, entered, hold = session.execute, asyncio.Event(), asyncio.Event()

        async def blocked(*args, **kwargs):
            result = await execute(*args, **kwargs)
            entered.set()
            await hold.wait()
            return result

        monkeypatch.setattr(session, "execute", blocked)
        stream = repository.aiter_inbound_for_owner_pages(session, scope, global_id_order=True)
        with observe(session, repository, monkeypatch) as (_, validations, checks):
            task = asyncio.create_task(anext(stream))
            await entered.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            await stream.aclose()
            assert validations == [401] and len(checks) == 1
            scope.transaction.assert_current(session)
